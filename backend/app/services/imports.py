"""Bank-account registry and the file-import pipeline.

The pipeline is deliberately one function deep: validate the request, reserve an
idempotency slot, store the original privately, interpret every row, insert the
valid movements and record the rejected rows. A retry re-reads the stored
original, so it cannot invent different data than the first attempt.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.imports.mapping import (
    ColumnMapping,
    ImportOptions,
    MappingError,
    RowProblem,
    build_movement,
    validate_mapping,
)
from app.imports.storage import ImportStorage, ImportStorageError
from app.imports.tabular import ImportFileError, Table, read_table
from app.models import (
    BankAccount,
    BankTransaction,
    ImportJob,
    ImportRowError,
    ImportSourceType,
    ImportStatus,
    LedgerTransaction,
)
from app.services import audit

#: Bound on stored row errors. Beyond this the summary carries the count; a
#: 50k-row file must not turn one bad column into 50k error rows.
MAX_STORED_ROW_ERRORS = 5_000

ERROR_SUMMARY_MAX_LENGTH = 1000
ERROR_MESSAGE_MAX_LENGTH = 300
FILE_NAME_MAX_LENGTH = 255
CONTENT_TYPE_MAX_LENGTH = 120
ACCOUNT_NAME_MAX_LENGTH = 120
BANK_NAME_MAX_LENGTH = 120
MASKED_NUMBER_MAX_LENGTH = 32
LEDGER_CODE_MAX_LENGTH = 32
EXTERNAL_ID_MAX_LENGTH = 100
SOURCE_SYSTEM_MAX_LENGTH = 50
DEFAULT_SOURCE_SYSTEM = "file_import"

SUPPORTED_UPLOAD_SOURCES = frozenset(
    {ImportSourceType.BANK_STATEMENT, ImportSourceType.LEDGER_EXPORT}
)


class ImportServiceError(ValueError):
    """A request the service refuses, translated to an HTTP status by the route."""


class BankAccountNotFoundError(ImportServiceError):
    pass


class BankAccountInactiveError(ImportServiceError):
    pass


class DuplicateImportError(ImportServiceError):
    def __init__(self, existing_job_id: UUID | None) -> None:
        super().__init__("This file was already imported with the same interpretation.")
        self.existing_job_id = existing_job_id


class ImportNotFoundError(ImportServiceError):
    pass


class ImportNotRetryableError(ImportServiceError):
    pass


class ImportRequestError(ImportServiceError):
    pass


class PayloadTooLargeError(ImportRequestError):
    pass


class StoredFileUnavailableError(ImportServiceError):
    pass


def create_bank_account(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    account_name: str,
    bank_name: str,
    account_number_masked: str | None = None,
    currency: str = "COP",
    ledger_account_code: str | None = None,
    external_account_id: str | None = None,
    connection_id: UUID | None = None,
) -> BankAccount:
    """Register a bank account. The number is stored only masked."""
    account = BankAccount(
        organization_id=organization_id,
        connection_id=connection_id,
        account_name=_required(account_name, "account_name", ACCOUNT_NAME_MAX_LENGTH),
        bank_name=_required(bank_name, "bank_name", BANK_NAME_MAX_LENGTH),
        account_number_masked=_optional(
            account_number_masked, "account_number_masked", MASKED_NUMBER_MAX_LENGTH
        ),
        currency=_currency(currency),
        ledger_account_code=_optional(
            ledger_account_code, "ledger_account_code", LEDGER_CODE_MAX_LENGTH
        ),
        external_account_id=_optional(
            external_account_id, "external_account_id", EXTERNAL_ID_MAX_LENGTH
        ),
        active=True,
    )
    db.add(account)
    db.flush()

    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="bank_account.created",
        entity_type="bank_account",
        entity_id=account.id,
        metadata={"bank_name": account.bank_name, "currency": account.currency},
    )
    db.flush()
    return account


def list_bank_accounts(
    db: Session, *, organization_id: UUID, include_inactive: bool = False
) -> list[BankAccount]:
    statement = select(BankAccount).where(BankAccount.organization_id == organization_id)
    if not include_inactive:
        statement = statement.where(BankAccount.active.is_(True))
    return list(db.scalars(statement.order_by(BankAccount.created_at, BankAccount.id)))


def get_bank_account(
    db: Session, *, organization_id: UUID, bank_account_id: UUID
) -> BankAccount | None:
    account = db.get(BankAccount, bank_account_id)
    if account is None or account.organization_id != organization_id:
        return None
    return account


def create_import(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    bank_account_id: UUID,
    source_type: ImportSourceType,
    file_name: str,
    content_type: str,
    data: bytes,
    mapping: ColumnMapping,
    options: ImportOptions,
    storage: ImportStorage,
    max_bytes: int,
    max_rows: int,
) -> ImportJob:
    """Validate, store and process one upload."""
    account = get_bank_account(db, organization_id=organization_id, bank_account_id=bank_account_id)
    if account is None:
        raise BankAccountNotFoundError("Bank account not found.")
    if not account.active:
        raise BankAccountInactiveError("The bank account is inactive.")
    if source_type not in SUPPORTED_UPLOAD_SOURCES:
        raise ImportRequestError("Only bank_statement and ledger_export can be uploaded as files.")
    if not data:
        raise ImportRequestError("The file is empty.")
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"The file exceeds the {max_bytes} byte limit.")

    safe_name = _file_name(file_name)
    file_sha256 = hashlib.sha256(data).hexdigest()
    request_sha256 = _request_hash(file_sha256, mapping, options)

    existing = db.scalar(
        select(ImportJob).where(
            ImportJob.organization_id == organization_id,
            ImportJob.bank_account_id == bank_account_id,
            ImportJob.source_type == source_type,
            ImportJob.file_sha256 == file_sha256,
            ImportJob.request_sha256 == request_sha256,
        )
    )
    if existing is not None:
        raise DuplicateImportError(existing.id)

    table = _read_table(data, file_name=safe_name, content_type=content_type, max_rows=max_rows)
    _validate_mapping(table, mapping, source_type)

    job = ImportJob(
        organization_id=organization_id,
        bank_account_id=bank_account_id,
        source_type=source_type,
        file_name=safe_name,
        file_sha256=file_sha256,
        request_sha256=request_sha256,
        storage_key="",
        content_type=(content_type or "application/octet-stream")[:CONTENT_TYPE_MAX_LENGTH],
        status=ImportStatus.PROCESSING,
        mapping_json=mapping.model_dump(mode="json"),
        options_json=options.model_dump(mode="json"),
        created_by=actor_id,
    )

    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError as exc:
        # Two requests raced on the same idempotency key. The winner is the one
        # whose row exists; the loser reports it instead of importing twice.
        winner = db.scalar(
            select(ImportJob).where(
                ImportJob.organization_id == organization_id,
                ImportJob.bank_account_id == bank_account_id,
                ImportJob.source_type == source_type,
                ImportJob.file_sha256 == file_sha256,
                ImportJob.request_sha256 == request_sha256,
            )
        )
        raise DuplicateImportError(winner.id if winner is not None else None) from exc

    storage_key = f"{organization_id}/{job.id}{Path(safe_name).suffix.lower()}"
    try:
        storage.save(storage_key, data)
    except ImportStorageError as exc:
        raise StoredFileUnavailableError(str(exc)) from exc
    job.storage_key = storage_key

    _process(db, job, table=table, mapping=mapping, options=options)
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action=f"import.{job.status.value}",
        entity_type="import_job",
        entity_id=job.id,
        metadata={
            "source_type": job.source_type.value,
            "file_name": job.file_name,
            "rows_read": job.rows_read,
            "rows_imported": job.rows_imported,
            "errors": job.rows_read - job.rows_imported,
        },
    )
    db.flush()
    return job


def retry_import(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    import_id: UUID,
    storage: ImportStorage,
    max_rows: int,
) -> ImportJob:
    """Reprocess a failed job from its stored original.

    Only a job that imported zero rows may be retried. Re-running a partial
    import would duplicate the rows that already succeeded.
    """
    job = get_import(db, organization_id=organization_id, import_id=import_id)
    if job is None:
        raise ImportNotFoundError("Import not found.")
    if job.status is not ImportStatus.FAILED:
        raise ImportNotRetryableError(
            "Only a failed import can be retried; upload a corrected file instead."
        )
    if job.rows_imported:
        raise ImportNotRetryableError(
            "The import already wrote rows; retrying would duplicate them."
        )

    account = get_bank_account(
        db, organization_id=organization_id, bank_account_id=job.bank_account_id
    )
    if account is None:
        raise BankAccountNotFoundError("Bank account not found.")
    if not account.active:
        raise BankAccountInactiveError("The bank account is inactive.")

    try:
        data = storage.read(job.storage_key)
    except ImportStorageError as exc:
        raise StoredFileUnavailableError(str(exc)) from exc

    table = _read_table(
        data, file_name=job.file_name, content_type=job.content_type, max_rows=max_rows
    )
    mapping = ColumnMapping.model_validate(job.mapping_json)
    options = ImportOptions.model_validate(job.options_json)
    _validate_mapping(table, mapping, job.source_type)

    db.execute(delete(ImportRowError).where(ImportRowError.import_job_id == job.id))
    job.status = ImportStatus.PROCESSING
    job.rows_read = 0
    job.rows_imported = 0
    job.error_summary = None
    job.completed_at = None

    _process(db, job, table=table, mapping=mapping, options=options)
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="import.retried",
        entity_type="import_job",
        entity_id=job.id,
        metadata={
            "status": job.status.value,
            "rows_read": job.rows_read,
            "rows_imported": job.rows_imported,
        },
    )
    db.flush()
    return job


def get_import(db: Session, *, organization_id: UUID, import_id: UUID) -> ImportJob | None:
    job = db.get(ImportJob, import_id)
    if job is None or job.organization_id != organization_id:
        return None
    return job


def list_imports(
    db: Session,
    *,
    organization_id: UUID,
    bank_account_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[ImportJob], int]:
    filters = [ImportJob.organization_id == organization_id]
    if bank_account_id is not None:
        filters.append(ImportJob.bank_account_id == bank_account_id)

    total = db.scalar(select(func.count()).select_from(ImportJob).where(*filters))
    jobs = list(
        db.scalars(
            select(ImportJob)
            .where(*filters)
            .order_by(ImportJob.created_at.desc(), ImportJob.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return jobs, int(total or 0)


def list_import_errors(
    db: Session, *, organization_id: UUID, import_id: UUID, limit: int, offset: int
) -> tuple[list[ImportRowError], int]:
    job = get_import(db, organization_id=organization_id, import_id=import_id)
    if job is None:
        raise ImportNotFoundError("Import not found.")

    total = db.scalar(
        select(func.count())
        .select_from(ImportRowError)
        .where(ImportRowError.import_job_id == job.id)
    )
    rows = list(
        db.scalars(
            select(ImportRowError)
            .where(ImportRowError.import_job_id == job.id)
            .order_by(ImportRowError.row_number, ImportRowError.field)
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total or 0)


def _process(
    db: Session,
    job: ImportJob,
    *,
    table: Table,
    mapping: ColumnMapping,
    options: ImportOptions,
) -> None:
    errors: list[ImportRowError] = []
    imported = 0

    for row in table.rows:
        try:
            movement = build_movement(row, mapping, options, source_type=job.source_type)
        except RowProblem as problem:
            errors.append(
                ImportRowError(
                    organization_id=job.organization_id,
                    import_job_id=job.id,
                    row_number=row.number,
                    field=problem.field,
                    message=problem.message[:ERROR_MESSAGE_MAX_LENGTH],
                )
            )
            continue

        if job.source_type == ImportSourceType.BANK_STATEMENT:
            db.add(
                BankTransaction(
                    organization_id=job.organization_id,
                    bank_account_id=job.bank_account_id,
                    import_job_id=job.id,
                    transaction_date=movement.transaction_date,
                    value_date=movement.value_date,
                    amount_minor=movement.amount_minor,
                    direction=movement.direction,
                    reference=movement.reference,
                    description=movement.description,
                    external_id=movement.external_id,
                    fingerprint=movement.fingerprint,
                )
            )
        else:
            db.add(
                LedgerTransaction(
                    organization_id=job.organization_id,
                    bank_account_id=job.bank_account_id,
                    import_job_id=job.id,
                    source_system=(options.source_system or DEFAULT_SOURCE_SYSTEM)[
                        :SOURCE_SYSTEM_MAX_LENGTH
                    ],
                    external_id=movement.external_id,
                    transaction_date=movement.transaction_date,
                    amount_minor=movement.amount_minor,
                    direction=movement.direction,
                    reference=movement.reference,
                    description=movement.description,
                    fingerprint=movement.fingerprint,
                )
            )
        imported += 1

    for error in errors[:MAX_STORED_ROW_ERRORS]:
        db.add(error)

    job.rows_read = len(table.rows)
    job.rows_imported = imported
    job.status = ImportStatus.COMPLETED if imported else ImportStatus.FAILED
    job.completed_at = datetime.now(UTC)

    if not table.rows:
        job.error_summary = "The file has no data rows."
    elif errors:
        summary = f"{len(errors)} of {len(table.rows)} rows were rejected."
        if len(errors) > MAX_STORED_ROW_ERRORS:
            summary += f" The first {MAX_STORED_ROW_ERRORS} errors are listed."
        job.error_summary = summary[:ERROR_SUMMARY_MAX_LENGTH]
    else:
        job.error_summary = None

    db.flush()


def _read_table(data: bytes, *, file_name: str, content_type: str, max_rows: int) -> Table:
    try:
        return read_table(data, file_name=file_name, content_type=content_type, max_rows=max_rows)
    except ImportFileError as exc:
        raise ImportRequestError(str(exc)) from exc


def _validate_mapping(table: Table, mapping: ColumnMapping, source_type: ImportSourceType) -> None:
    try:
        validate_mapping(table.headers, mapping, source_type=source_type)
    except MappingError as exc:
        raise ImportRequestError(str(exc)) from exc


def _request_hash(file_sha256: str, mapping: ColumnMapping, options: ImportOptions) -> str:
    payload = json.dumps(
        {
            "file_sha256": file_sha256,
            "mapping": mapping.model_dump(mode="json"),
            "options": options.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_name(value: str) -> str:
    """Keep the base name only: a client-supplied path is not part of the data."""
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        raise ImportRequestError("The file has no name.")
    if len(name) > FILE_NAME_MAX_LENGTH:
        raise ImportRequestError("The file name is too long.")
    return name


def _required(value: str, field: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ImportRequestError(f"{field} is required.")
    if len(cleaned) > max_length:
        raise ImportRequestError(f"{field} exceeds {max_length} characters.")
    return cleaned


def _optional(value: str | None, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ImportRequestError(f"{field} exceeds {max_length} characters.")
    return cleaned


def _currency(value: str) -> str:
    currency = (value or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ImportRequestError("currency must be a three-letter ISO code.")
    return currency


# Re-exported for callers that only import the service.
__all__ = [
    "BankAccountInactiveError",
    "BankAccountNotFoundError",
    "DuplicateImportError",
    "ImportNotFoundError",
    "ImportNotRetryableError",
    "ImportRequestError",
    "ImportServiceError",
    "PayloadTooLargeError",
    "StoredFileUnavailableError",
    "create_bank_account",
    "create_import",
    "get_bank_account",
    "get_import",
    "list_bank_accounts",
    "list_import_errors",
    "list_imports",
    "retry_import",
]
