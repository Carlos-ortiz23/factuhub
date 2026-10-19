"""Bank-account and import endpoints.

Uploads are multipart. `mapping` and `options` arrive as JSON strings because a
multipart form has no nested-object type; they are parsed into their Pydantic
models here and a malformed value is a 422 whose message names the field, never
a 500.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.api.deps import (
    OrganizationContext,
    get_app_settings,
    get_db_session,
    get_import_storage,
    require_csrf,
    require_permission,
)
from app.api.scoping import require_bank_account_permission, require_import_permission
from app.core.config import Settings
from app.core.permissions import Permission
from app.imports.mapping import ColumnMapping, ImportOptions
from app.imports.storage import ImportStorage
from app.models import BankAccount, ImportJob, ImportSourceType, ProviderCredential
from app.schemas.imports import (
    BankAccountCreateRequest,
    BankAccountListResponse,
    BankAccountResponse,
    ImportListResponse,
    ImportResponse,
    ImportRowErrorListResponse,
    ImportRowErrorResponse,
)
from app.services import imports as imports_service

router = APIRouter(tags=["imports"])


def _translate(exc: imports_service.ImportServiceError) -> HTTPException:
    if isinstance(exc, imports_service.PayloadTooLargeError):
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    if isinstance(
        exc,
        (imports_service.BankAccountNotFoundError, imports_service.ImportNotFoundError),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(
        exc,
        (
            imports_service.BankAccountInactiveError,
            imports_service.ImportNotRetryableError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, imports_service.DuplicateImportError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "existing_import_id": (str(exc.existing_job_id) if exc.existing_job_id else None),
            },
        )
    if isinstance(exc, imports_service.StoredFileUnavailableError):
        # The stored original is missing or unreadable: a server-side condition,
        # not something the client can fix by changing the request.
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _as_account(row: BankAccount) -> BankAccountResponse:
    return BankAccountResponse.model_validate(row)


def _as_import(job: ImportJob) -> ImportResponse:
    return ImportResponse(
        id=job.id,
        organization_id=job.organization_id,
        bank_account_id=job.bank_account_id,
        source_type=job.source_type,
        file_name=job.file_name,
        status=job.status,
        rows_read=job.rows_read,
        rows_imported=job.rows_imported,
        error_summary=job.error_summary,
        mapping=job.mapping_json,
        options=job.options_json,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _parse_form_model[ModelT: BaseModel](
    raw: str | None, model: type[ModelT], field: str, *, optional: bool = False
) -> ModelT:
    if raw is None or not raw.strip():
        if optional:
            return model.model_validate({})  # type: ignore[call-arg]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} is required.",
        )

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} is not valid JSON.",
        ) from None

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be a JSON object.",
        )

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        # Only the location and the message: the app-wide handler does the same
        # for request bodies, and echoing `input` back is unnecessary here too.
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or field}: {error['msg']}"
            for error in exc.errors()
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {field}: {reasons}",
        ) from None


@router.get(
    "/organizations/{organization_id}/bank-accounts",
    response_model=BankAccountListResponse,
    summary="List the company's bank accounts",
)
def list_bank_accounts(
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
    include_inactive: Annotated[bool, Query()] = False,
) -> BankAccountListResponse:
    rows = imports_service.list_bank_accounts(
        db, organization_id=context.organization_id, include_inactive=include_inactive
    )
    return BankAccountListResponse(accounts=[_as_account(row) for row in rows])


@router.post(
    "/organizations/{organization_id}/bank-accounts",
    response_model=BankAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a bank account",
    description=(
        "Requires `manage_integrations`. Only a masked account number is stored; "
        "the full number is never needed to reconcile."
    ),
)
def create_bank_account(
    payload: BankAccountCreateRequest,
    context: Annotated[
        OrganizationContext, Depends(require_permission(Permission.MANAGE_INTEGRATIONS))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> BankAccountResponse:
    if payload.connection_id is not None:
        # A connection from another company must not be attachable. The service
        # does not need to know about provider credentials to enforce this.
        connection = db.get(ProviderCredential, payload.connection_id)
        if connection is None or connection.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider connection not found.",
            )

    try:
        account = imports_service.create_bank_account(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            account_name=payload.account_name,
            bank_name=payload.bank_name,
            account_number_masked=payload.account_number_masked,
            currency=payload.currency,
            ledger_account_code=payload.ledger_account_code,
            external_account_id=payload.external_account_id,
            connection_id=payload.connection_id,
        )
    except imports_service.ImportServiceError as exc:
        raise _translate(exc) from exc

    response = _as_account(account)
    db.commit()
    return response


@router.get(
    "/bank-accounts/{account_id}",
    response_model=BankAccountResponse,
    summary="One bank account",
)
def get_bank_account(
    account_id: UUID,
    context: Annotated[
        OrganizationContext, Depends(require_bank_account_permission(Permission.READ))
    ],
    db: Annotated[Session, Depends(get_db_session)],
) -> BankAccountResponse:
    account = imports_service.get_bank_account(
        db, organization_id=context.organization_id, bank_account_id=account_id
    )
    if account is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found.")
    return _as_account(account)


@router.post(
    "/organizations/{organization_id}/imports",
    response_model=ImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a bank statement or ledger export",
    description=(
        "Requires `import`. The file is read with the explicit column mapping and "
        "options; valid rows are imported, rejected rows are reported per line. "
        "Uploading the same bytes with the same interpretation is a 409."
    ),
    responses={
        409: {"description": "The same file was already imported with this interpretation"},
        413: {"description": "The file exceeds the configured limit"},
        422: {"description": "Unreadable file, missing columns, or invalid mapping"},
    },
)
def create_import(
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.IMPORT))],
    db: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[ImportStorage, Depends(get_import_storage)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    file: Annotated[UploadFile, File()],
    source_type: Annotated[ImportSourceType, Form()],
    bank_account_id: Annotated[UUID, Form()],
    mapping: Annotated[str, Form()],
    options: Annotated[str | None, Form()] = None,
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> ImportResponse:
    parsed_mapping = _parse_form_model(mapping, ColumnMapping, "mapping")
    parsed_options = _parse_form_model(options, ImportOptions, "options", optional=True)

    # Read one byte past the limit so an oversized upload is detected without
    # buffering it whole.
    data = file.file.read(settings.import_max_bytes + 1)

    try:
        job = imports_service.create_import(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            bank_account_id=bank_account_id,
            source_type=source_type,
            file_name=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            mapping=parsed_mapping,
            options=parsed_options,
            storage=storage,
            max_bytes=settings.import_max_bytes,
            max_rows=settings.import_max_rows,
        )
    except imports_service.ImportServiceError as exc:
        raise _translate(exc) from exc

    db.refresh(job)
    response = _as_import(job)
    db.commit()
    return response


@router.get(
    "/organizations/{organization_id}/imports",
    response_model=ImportListResponse,
    summary="List the company's imports",
)
def list_imports(
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
    bank_account_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ImportListResponse:
    jobs, total = imports_service.list_imports(
        db,
        organization_id=context.organization_id,
        bank_account_id=bank_account_id,
        limit=limit,
        offset=offset,
    )
    return ImportListResponse(
        imports=[_as_import(job) for job in jobs], total=total, limit=limit, offset=offset
    )


@router.get(
    "/imports/{import_id}",
    response_model=ImportResponse,
    summary="One import job",
)
def get_import(
    import_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_import_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
) -> ImportResponse:
    job = imports_service.get_import(
        db, organization_id=context.organization_id, import_id=import_id
    )
    if job is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found.")
    return _as_import(job)


@router.get(
    "/imports/{import_id}/errors",
    response_model=ImportRowErrorListResponse,
    summary="The rows an import rejected",
)
def list_import_errors(
    import_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_import_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ImportRowErrorListResponse:
    try:
        rows, total = imports_service.list_import_errors(
            db,
            organization_id=context.organization_id,
            import_id=import_id,
            limit=limit,
            offset=offset,
        )
    except imports_service.ImportServiceError as exc:
        raise _translate(exc) from exc

    return ImportRowErrorListResponse(
        errors=[
            ImportRowErrorResponse(row_number=row.row_number, field=row.field, message=row.message)
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/imports/{import_id}/retry",
    response_model=ImportResponse,
    summary="Reprocess a failed import",
    description=(
        "Requires `import`. Only a job that imported zero rows is retryable: "
        "re-running a partial import would duplicate what already succeeded."
    ),
    responses={409: {"description": "The import is not retryable"}},
)
def retry_import(
    import_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_import_permission(Permission.IMPORT))],
    db: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[ImportStorage, Depends(get_import_storage)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> ImportResponse:
    try:
        job = imports_service.retry_import(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            import_id=import_id,
            storage=storage,
            max_rows=settings.import_max_rows,
        )
    except imports_service.ImportServiceError as exc:
        raise _translate(exc) from exc

    db.refresh(job)
    response = _as_import(job)
    db.commit()
    return response
