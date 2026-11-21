from collections.abc import Mapping
from dataclasses import dataclass

from batches.timings import ChangeoverTiming
from costs.policies import WorkPolicy, to_work_units


@dataclass(frozen=True, slots=True)
class NormalizedChangeover:
    timing_id: str
    start_segment: str
    end_segment: str
    work: int


def normalize_changeovers(timings: tuple[ChangeoverTiming, ...], policy: WorkPolicy) -> tuple[NormalizedChangeover, ...]:
    return tuple(
        NormalizedChangeover(
            timing.timing_id,
            timing.start_segment,
            timing.end_segment,
            to_work_units(policy, timing.amount, timing.unit),
        )
        for timing in timings
    )


def applies_changeover(timing: NormalizedChangeover, plan: Mapping[str, str]) -> bool:
    return plan[timing.start_segment] == 'retest' and plan[timing.end_segment] == 'release'
