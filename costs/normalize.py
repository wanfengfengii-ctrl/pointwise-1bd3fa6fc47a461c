from dataclasses import dataclass

from batches.revisions import BatchRevision
from costs.changeovers import NormalizedChangeover, normalize_changeovers
from costs.policies import WorkPolicy, to_work_units


@dataclass(frozen=True, slots=True)
class NormalizedBaseTiming:
    timing_id: str
    segment_id: str
    disposition: str
    work: int


@dataclass(frozen=True, slots=True)
class CostBasis:
    revision_id: str
    policy_version: str
    segment_ids: tuple[str, ...]
    base_timings: tuple[NormalizedBaseTiming, ...]
    changeovers: tuple[NormalizedChangeover, ...]


def normalize_basis(revision: BatchRevision, policy: WorkPolicy) -> CostBasis:
    bases = tuple(
        NormalizedBaseTiming(
            timing.timing_id,
            timing.segment_id,
            timing.disposition,
            to_work_units(policy, timing.amount, timing.unit),
        )
        for timing in revision.base_timings
    )
    return CostBasis(
        revision.revision_id,
        policy.version,
        tuple(segment.segment_id for segment in revision.segments),
        bases,
        normalize_changeovers(revision.changeovers, policy),
    )
