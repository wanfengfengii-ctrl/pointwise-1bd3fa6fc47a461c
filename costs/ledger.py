from collections.abc import Mapping
from dataclasses import dataclass
import sqlite3

from batches.store import BatchStore
from costs.changeovers import applies_changeover
from costs.normalize import CostBasis, normalize_basis
from costs.policies import get_policy


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    timing_id: str
    kind: str
    start_segment: str
    end_segment: str | None
    work: int


@dataclass(frozen=True, slots=True)
class ScoreResult:
    revision_id: str
    policy_version: str
    base_total: int
    changeover_total: int
    entries: tuple[LedgerEntry, ...]

    @property
    def total_work(self) -> int:
        return self.base_total + self.changeover_total


def score_basis(basis: CostBasis, plan: Mapping[str, str]) -> ScoreResult:
    if not isinstance(plan, Mapping) or set(plan) != set(basis.segment_ids):
        raise ValueError('the station plan must cover every segment exactly')
    if any(value not in ('retest', 'release') for value in plan.values()):
        raise ValueError('invalid station disposition')
    bases = tuple(
        LedgerEntry(timing.timing_id, 'base', timing.segment_id, None, timing.work)
        for timing in basis.base_timings
        if plan[timing.segment_id] == timing.disposition
    )
    extras = tuple(
        LedgerEntry(timing.timing_id, 'changeover', timing.start_segment, timing.end_segment, timing.work)
        for timing in basis.changeovers
        if applies_changeover(timing, plan)
    )
    return ScoreResult(
        basis.revision_id,
        basis.policy_version,
        sum(entry.work for entry in bases),
        sum(entry.work for entry in extras),
        bases + extras,
    )


def score_batch(connection: sqlite3.Connection, revision_id: str, policy_version: str, plan) -> ScoreResult:
    revision = BatchStore(connection).load_revision(revision_id)
    return score_basis(normalize_basis(revision, get_policy(policy_version)), plan)
