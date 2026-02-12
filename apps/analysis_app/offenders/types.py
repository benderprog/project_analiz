from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class OffenderMention:
    full_name: str
    second_name: str
    first_name: str
    patronymic_name: str
    birth_date: date | None
    birth_year: int | None
    span: tuple[int, int] | None
    source: str
    surface_text: str
    employee_context: bool = False


@dataclass(frozen=True)
class PortalOffender:
    full_name: str
    second_name: str
    first_name: str
    patronymic_name: str
    birth_date: date | None


@dataclass(frozen=True)
class MatchPair:
    mention: OffenderMention
    portal: PortalOffender
    match_type: str
    discrepancy: str | None = None


@dataclass(frozen=True)
class PossibleMatch:
    mention: OffenderMention
    portal: PortalOffender
    reason: str


@dataclass(frozen=True)
class AmbiguousMention:
    mention: OffenderMention
    reason: str


@dataclass
class OffenderMatchResult:
    matched_pairs: list[MatchPair] = field(default_factory=list)
    possible_matches: list[PossibleMatch] = field(default_factory=list)
    missing_in_portal: list[OffenderMention] = field(default_factory=list)
    missing_in_summary: list[PortalOffender] = field(default_factory=list)
    ambiguous_mentions: list[AmbiguousMention] = field(default_factory=list)
