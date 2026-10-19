"""Duplicate suspicion that never deletes anything.

§8.5 is explicit: date, amount and description alone are not enough, and the
engine must tell apart a repeated upload, the same movement imported again, two
legitimate similar transactions, and something that needs investigation. That is
why the fingerprint and the external document id participate in the decision, and
why this module only returns candidates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

from app.reconciliation.normalizer import economic_direction
from app.reconciliation.types import Movement


class DuplicateKind(StrEnum):
    SAME_IMPORT = "same_import"
    REIMPORTED = "reimported"
    DISTINCT_DOCUMENTS = "distinct_documents"
    POSSIBLE_DUPLICATE = "possible_duplicate"


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    left: Movement
    right: Movement
    kind: DuplicateKind
    reasons: tuple[str, ...]


def find_duplicate_candidates(movements: list[Movement]) -> list[DuplicateCandidate]:
    """Pair movements that share date, amount, direction and side, then classify.

    The shared key is only a cheap candidate filter; the classification uses the
    fingerprint and the external id. Two legitimate commission charges on the same
    day are therefore reported as `possible_duplicate` for a human to decide, not
    as a duplicate to remove.
    """
    buckets: dict[tuple, list[Movement]] = defaultdict(list)
    for movement in movements:
        buckets[
            (
                movement.side,
                movement.transaction_date,
                movement.amount_minor,
                economic_direction(movement.side, movement.direction),
            )
        ].append(movement)

    candidates: list[DuplicateCandidate] = []
    for group in buckets.values():
        for left, right in combinations(group, 2):
            candidates.append(_classify(left, right))
    return candidates


def _classify(left: Movement, right: Movement) -> DuplicateCandidate:
    same_fingerprint = bool(left.fingerprint) and left.fingerprint == right.fingerprint
    left_external = (left.external_id or "").strip()
    right_external = (right.external_id or "").strip()

    if same_fingerprint:
        if left.import_job_id is not None and left.import_job_id == right.import_job_id:
            kind = DuplicateKind.SAME_IMPORT
            reasons = ("same fingerprint inside one import job",)
        else:
            kind = DuplicateKind.REIMPORTED
            reasons = (
                "same fingerprint in different imports",
                "the same movement was imported again",
            )
        return DuplicateCandidate(left, right, kind, reasons)

    if left_external and right_external and left_external != right_external:
        return DuplicateCandidate(
            left,
            right,
            DuplicateKind.DISTINCT_DOCUMENTS,
            (
                "same date, amount and direction",
                f"different external documents ({left_external} vs {right_external})",
                "likely two legitimate transactions",
            ),
        )

    reasons = [
        "same date, amount and direction",
        "fingerprints differ",
    ]
    if left_external and right_external:
        reasons.append("the external document id is the same but the data differs")
    elif left_external or right_external:
        reasons.append("only one side carries an external document id")
    else:
        reasons.append("neither side carries an external document id")
    reasons.append("investigate before confirming")
    return DuplicateCandidate(left, right, DuplicateKind.POSSIBLE_DUPLICATE, tuple(reasons))
