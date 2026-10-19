"""Normalisation without ever rewriting the stored movement.

§8.1 asks for normalised dates, references and descriptions, exact amounts,
homogeneous debits and credits, preserved originals and repeated-import
detection. The originals stay in the database; everything here works on copies.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from app.models import TransactionDirection
from app.reconciliation.types import EconomicDirection, MovementSide

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_NON_WORD = re.compile(r"[^A-Z0-9]+")

#: Spanish filler that carries no identifying information in a bank description.
_STOPWORDS = frozenset(
    {
        "A",
        "AL",
        "CON",
        "DE",
        "DEL",
        "EL",
        "EN",
        "LA",
        "LAS",
        "LOS",
        "O",
        "PARA",
        "POR",
        "SU",
        "UN",
        "UNA",
        "Y",
    }
)


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_reference(value: str | None) -> str:
    """Upper-case alphanumerics only: `ABC-001` and `abc 001` are one reference."""
    if not value:
        return ""
    return _NON_ALNUM.sub("", strip_accents(value).upper())


def normalize_description(value: str | None) -> str:
    if not value:
        return ""
    text = _NON_WORD.sub(" ", strip_accents(value).upper())
    return " ".join(text.split())


def description_tokens(value: str | None) -> frozenset[str]:
    return frozenset(
        token for token in normalize_description(value).split() if token and token not in _STOPWORDS
    )


def description_similarity(left: str | None, right: str | None) -> float:
    """Jaccard similarity over meaningful words. 0 when either side is empty."""
    left_tokens = description_tokens(left)
    right_tokens = description_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union)


def economic_direction(side: MovementSide, direction: TransactionDirection) -> EconomicDirection:
    """What the movement did to the company's bank account.

    A bank credit is money in. On a ledger export of the bank's asset account,
    the accounting sign is the opposite: a debit increases the asset, a credit
    decreases it. Reading both through this function is what makes the two sides
    comparable without rewriting either `direction`.
    """
    if side is MovementSide.BANK:
        return (
            EconomicDirection.INFLOW
            if direction is TransactionDirection.CREDIT
            else EconomicDirection.OUTFLOW
        )
    return (
        EconomicDirection.INFLOW
        if direction is TransactionDirection.DEBIT
        else EconomicDirection.OUTFLOW
    )


def date_distance_days(left: date, right: date) -> int:
    return abs((left - right).days)


def date_span_days(dates: list[date]) -> int:
    if not dates:
        return 0
    return (max(dates) - min(dates)).days


def references_are_related(references: list[str | None], *, min_prefix: int = 3) -> bool:
    """Whether grouped references plausibly belong to one event.

    Exact equality is the strong case. A shared alphanumeric prefix of at least
    three characters covers invoice families (`FV001`, `FV002`). With fewer than
    two present references there is nothing to contradict the group.
    """
    normalized = [normalize_reference(reference) for reference in references]
    present = [value for value in normalized if value]
    if len(present) < 2:
        return True
    if len(set(present)) == 1:
        return True

    prefix = present[0]
    for value in present[1:]:
        limit = min(len(prefix), len(value))
        index = 0
        while index < limit and prefix[index] == value[index]:
            index += 1
        prefix = prefix[:index]
        if len(prefix) < min_prefix:
            return False
    return len(prefix) >= min_prefix
