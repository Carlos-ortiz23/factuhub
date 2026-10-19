"""Grouped candidates: one bank movement against several postings, or the reverse.

Groups are exact. A fee or an unexplained difference is never absorbed to make a
group balance (§8.4): the moment the sum is allowed to be "close", the engine
starts inventing relationships. What does not add up stays pending and is shown
as a difference.

The combinatorial space is bounded twice: at most `max_group_size` movements per
side and at most `max_candidates_per_anchor` candidates considered per anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from app.reconciliation.normalizer import (
    date_span_days,
    economic_direction,
    references_are_related,
)
from app.reconciliation.types import DEFAULT_CONFIG, MatchConfig, Movement

DEFAULT_MAX_GROUP_SIZE = 3
DEFAULT_MAX_CANDIDATES_PER_ANCHOR = 25


@dataclass(frozen=True, slots=True)
class GroupSuggestion:
    bank_movements: tuple[Movement, ...]
    ledger_movements: tuple[Movement, ...]
    total_minor: int
    date_span_days: int
    score: float
    reasons: tuple[str, ...]


def find_groups(
    bank_movements: list[Movement],
    ledger_movements: list[Movement],
    config: MatchConfig = DEFAULT_CONFIG,
    *,
    max_group_size: int = DEFAULT_MAX_GROUP_SIZE,
    max_candidates_per_anchor: int = DEFAULT_MAX_CANDIDATES_PER_ANCHOR,
) -> list[GroupSuggestion]:
    """Find one-to-many and many-to-one candidates with an exact sum."""
    if max_group_size < 2:
        raise ValueError("max_group_size must be at least 2")
    if max_candidates_per_anchor < 2:
        raise ValueError("max_candidates_per_anchor must be at least 2")

    suggestions: list[GroupSuggestion] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    for bank in bank_movements:
        candidates = _members_for(
            anchor=bank,
            others=ledger_movements,
            side="ledger",
            config=config,
            limit=max_candidates_per_anchor,
        )
        for group in _combinations_summing_to(
            anchor=bank,
            candidates=candidates,
            config=config,
            max_group_size=max_group_size,
        ):
            key = ("bank", tuple(sorted(str(member.id) for member in group)))
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(_suggestion(bank, group, config))

    for ledger in ledger_movements:
        candidates = _members_for(
            anchor=ledger,
            others=bank_movements,
            side="bank",
            config=config,
            limit=max_candidates_per_anchor,
        )
        for group in _combinations_summing_to(
            anchor=ledger,
            candidates=candidates,
            config=config,
            max_group_size=max_group_size,
        ):
            key = ("ledger", tuple(sorted(str(member.id) for member in group)))
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(_suggestion(ledger, group, config))

    return sorted(
        suggestions,
        key=lambda suggestion: (
            -suggestion.score,
            suggestion.date_span_days,
            str(suggestion.bank_movements[0].id),
        ),
    )


def _members_for(
    *,
    anchor: Movement,
    others: list[Movement],
    side: str,
    config: MatchConfig,
    limit: int,
) -> list[Movement]:
    direction = economic_direction(anchor.side, anchor.direction)
    candidates = [
        movement
        for movement in others
        if movement.side.value == side
        and movement.amount_minor < anchor.amount_minor
        and economic_direction(movement.side, movement.direction) is direction
        and abs((movement.transaction_date - anchor.transaction_date).days)
        <= config.date_window_days
    ]
    candidates.sort(
        key=lambda movement: (
            abs((movement.transaction_date - anchor.transaction_date).days),
            str(movement.id),
        )
    )
    return candidates[:limit]


def _combinations_summing_to(
    *,
    anchor: Movement,
    candidates: list[Movement],
    config: MatchConfig,
    max_group_size: int,
) -> list[list[Movement]]:
    groups: list[list[Movement]] = []
    for size in range(2, max_group_size + 1):
        for group in combinations(candidates, size):
            if sum(member.amount_minor for member in group) != anchor.amount_minor:
                continue
            dates = [anchor.transaction_date] + [member.transaction_date for member in group]
            if date_span_days(dates) > config.date_window_days:
                continue
            if not references_are_related(
                [anchor.reference] + [member.reference for member in group]
            ):
                continue
            groups.append(list(group))
    return groups


def _suggestion(anchor: Movement, group: list[Movement], config: MatchConfig) -> GroupSuggestion:
    total = sum(member.amount_minor for member in group)
    span = date_span_days([anchor.transaction_date] + [member.transaction_date for member in group])
    references = [anchor.reference] + [member.reference for member in group]
    reference_reason = (
        "no reference constrains the group"
        if len([reference for reference in references if reference]) < 2
        else "references are related"
    )

    if anchor.side.value == "bank":
        bank_movements = (anchor,)
        ledger_movements = tuple(group)
    else:
        bank_movements = tuple(group)
        ledger_movements = (anchor,)

    return GroupSuggestion(
        bank_movements=bank_movements,
        ledger_movements=ledger_movements,
        total_minor=total,
        date_span_days=span,
        score=1.0,
        reasons=(
            f"{len(group)} movements sum exactly to {total} minor units",
            f"dates span {span} day(s) (window {config.date_window_days})",
            reference_reason,
            "group size bounded; no fee or difference was absorbed",
        ),
    )
