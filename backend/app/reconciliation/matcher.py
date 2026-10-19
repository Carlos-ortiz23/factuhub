"""Exact and approximate matching between one bank movement and ledger postings.

Two rules come before any score: the economic directions must agree and the
amounts must differ by no more than the configured tolerance. The score orders
the survivors; it never turns an incompatible pair into a candidate (§8.3).

When a component is unavailable — a statement without a reference, for example —
its weight is redistributed over the components that do exist. Scoring it as zero
would make every reference-less file unable to reach the suggestion band, which
is a data-quality accident, not evidence against the match.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

from app.reconciliation.normalizer import (
    date_distance_days,
    description_similarity,
    economic_direction,
    normalize_reference,
)
from app.reconciliation.types import (
    DEFAULT_CONFIG,
    MatchBand,
    MatchConfig,
    Movement,
    MovementSide,
)


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    bank: Movement
    ledger: Movement
    score: float
    band: MatchBand
    amount_difference_minor: int
    date_distance_days: int
    components: dict[str, float | None]
    reasons: tuple[str, ...]


def score_candidate(
    bank: Movement, ledger: Movement, config: MatchConfig = DEFAULT_CONFIG
) -> ScoredCandidate | None:
    """Score one pair, or return `None` when a hard rule excludes it."""
    if bank.side is not MovementSide.BANK or ledger.side is not MovementSide.LEDGER:
        raise ValueError("score_candidate expects a bank movement and a ledger movement")

    if economic_direction(bank.side, bank.direction) is not economic_direction(
        ledger.side, ledger.direction
    ):
        return None

    days = date_distance_days(bank.transaction_date, ledger.transaction_date)
    if days > config.date_window_days:
        return None

    difference = abs(bank.amount_minor - ledger.amount_minor)
    if difference > config.amount_tolerance_minor:
        return None

    amount_score = _amount_score(difference, config.amount_tolerance_minor)
    date_score = _date_score(days, config.date_window_days)

    bank_reference = normalize_reference(bank.reference)
    ledger_reference = normalize_reference(ledger.reference)
    reference_score: float | None = None
    if bank_reference and ledger_reference:
        reference_score = 1.0 if bank_reference == ledger_reference else 0.0

    description_score: float | None = None
    if bank.description and ledger.description:
        description_score = description_similarity(bank.description, ledger.description)

    components: dict[str, float | None] = {
        "amount": amount_score,
        "date": date_score,
        "reference": reference_score,
        "description": description_score,
    }
    score = _weighted_score(components, config)
    band = _band(score, config)

    return ScoredCandidate(
        bank=bank,
        ledger=ledger,
        score=score,
        band=band,
        amount_difference_minor=difference,
        date_distance_days=days,
        components=components,
        reasons=_reasons(
            difference=difference,
            days=days,
            config=config,
            reference_score=reference_score,
            description_score=description_score,
            band=band,
        ),
    )


def exact_candidates(
    bank: Movement,
    ledgers: list[Movement],
    config: MatchConfig = DEFAULT_CONFIG,
) -> list[ScoredCandidate]:
    """Candidates that satisfy §8.2's rules, without picking one arbitrarily.

    The date window applies here too: the specification says "fecha igual o
    dentro de una ventana configurable", and a bank posting one business day
    later is still the same payment.
    """
    candidates: list[ScoredCandidate] = []
    for ledger in ledgers:
        if ledger.amount_minor != bank.amount_minor:
            continue
        if economic_direction(bank.side, bank.direction) is not economic_direction(
            ledger.side, ledger.direction
        ):
            continue
        if (
            date_distance_days(bank.transaction_date, ledger.transaction_date)
            > config.date_window_days
        ):
            continue

        bank_reference = normalize_reference(bank.reference)
        ledger_reference = normalize_reference(ledger.reference)
        if bank_reference and ledger_reference and bank_reference != ledger_reference:
            continue

        scored = score_candidate(bank, ledger, config)
        if scored is not None:
            candidates.append(scored)

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.date_distance_days,
            candidate.ledger.transaction_date,
            str(candidate.ledger.id),
        ),
    )


def suggest_candidates(
    bank: Movement,
    ledgers: list[Movement],
    config: MatchConfig = DEFAULT_CONFIG,
    *,
    include_low: bool = False,
) -> list[ScoredCandidate]:
    """Every compatible candidate, strongest first.

    `include_low=True` implements "mostrar bajo solicitud": pairs below the
    suggestion band are still explainable even when they are not offered.
    """
    candidates = [
        candidate
        for ledger in ledgers
        if (candidate := score_candidate(bank, ledger, config)) is not None
        and (include_low or candidate.band is not MatchBand.LOW)
    ]
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            candidate.date_distance_days,
            str(candidate.ledger.id),
        ),
    )


def equivalent_top_candidates(candidates: list[ScoredCandidate], *, epsilon: float = 1e-9) -> bool:
    """Whether the two strongest candidates tie, which forbids picking one."""
    if len(candidates) < 2:
        return False
    return abs(candidates[0].score - candidates[1].score) <= epsilon


def top_candidates(candidates: list[ScoredCandidate], limit: int = 5) -> list[ScoredCandidate]:
    return list(islice(candidates, limit))


def _amount_score(difference: int, tolerance: int) -> float:
    if difference == 0:
        return 1.0
    if tolerance == 0:
        return 0.0
    # At the edge of the tolerance the amount contributes half of its weight:
    # a 5,000 COP difference is a fee to investigate, not a near-perfect match.
    return max(0.0, 1.0 - difference / (2 * tolerance))


def _date_score(days: int, window: int) -> float:
    if days == 0:
        return 1.0
    if window == 0:
        return 0.0
    return max(0.0, 1.0 - days / (window + 1))


def _weighted_score(components: dict[str, float | None], config: MatchConfig) -> float:
    available = {name: value for name, value in components.items() if value is not None}
    total_weight = sum(config.weight_of(name) for name in available)
    if total_weight == 0:
        return 0.0
    return sum(config.weight_of(name) * value for name, value in available.items()) / total_weight


def _band(score: float, config: MatchConfig) -> MatchBand:
    if score >= config.high_confidence_threshold:
        return MatchBand.HIGH
    if score >= config.suggestion_threshold:
        return MatchBand.SUGGESTION
    return MatchBand.LOW


def _reasons(
    *,
    difference: int,
    days: int,
    config: MatchConfig,
    reference_score: float | None,
    description_score: float | None,
    band: MatchBand,
) -> tuple[str, ...]:
    reasons: list[str] = []
    reasons.append(
        "amounts are identical"
        if difference == 0
        else (
            f"amounts differ by {difference} minor units "
            f"(tolerance {config.amount_tolerance_minor})"
        )
    )
    reasons.append(
        "dates are identical"
        if days == 0
        else f"dates differ by {days} day(s) (window {config.date_window_days})"
    )

    if reference_score is None:
        reasons.append("reference absent on one side; its weight is redistributed")
    elif reference_score == 1.0:
        reasons.append("references match")
    else:
        reasons.append("references differ")

    if description_score is None:
        reasons.append("description absent on one side; its weight is redistributed")
    elif description_score == 1.0:
        reasons.append("descriptions match")
    else:
        reasons.append(f"description similarity {description_score:.2f}")

    reasons.append(f"band: {band.value}")
    return tuple(reasons)
