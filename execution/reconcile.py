from dataclasses import dataclass

from execution.intake import ActualDisposition


@dataclass(frozen=True, slots=True)
class SegmentFinding:
    segment_id: str
    kind: str
    planned: str
    actual: str | None


def reconcile_plan(
    plan: tuple[tuple[str, str], ...], actuals: tuple[ActualDisposition, ...],
) -> tuple[SegmentFinding, ...]:
    by_segment = {actual.segment_id: actual.disposition for actual in actuals}
    findings = []
    for segment_id, planned in plan:
        actual = by_segment.get(segment_id)
        if actual is None:
            findings.append(SegmentFinding(segment_id, 'missing', planned, None))
        elif actual != planned:
            findings.append(SegmentFinding(segment_id, 'different', planned, actual))
    return tuple(findings)
