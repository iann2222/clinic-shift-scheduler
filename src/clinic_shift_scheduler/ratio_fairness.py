"""Shared integer ratio rules for formal v1 fairness calculations."""

from __future__ import annotations

BASIS_POINTS_SCALE = 10_000


def ratio_basis_points(numerator: int, denominator: int) -> int | None:
    """Return a half-up rounded ratio in basis points, or ``None`` for 0/0.

    Formal pattern ratios always have a non-negative numerator no greater than
    the attendance-day denominator.  Keeping this helper independent from the
    solver lets optimization, reporting, and validation share the exact rule.
    """

    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    if denominator < 0:
        raise ValueError("denominator must be non-negative")
    if denominator == 0:
        if numerator != 0:
            raise ValueError("a zero denominator requires a zero numerator")
        return None
    if numerator > denominator:
        raise ValueError("numerator must not exceed denominator")
    return (
        numerator * BASIS_POINTS_SCALE + denominator // 2
    ) // denominator
