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


def reconcile_work_order(
    assignment: tuple[tuple[str, str, str], ...],
    actuals: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[str, str], ...]:
    reported = {segment_id: (disposition, slot_id) for segment_id, disposition, slot_id in actuals}
    findings = []
    for segment_id, disposition, slot_id in assignment:
        actual = reported.get(segment_id)
        if actual is None:
            findings.append((segment_id, 'missing'))
            continue
        actual_disposition, actual_slot = actual
        if actual_disposition != disposition:
            findings.append((segment_id, 'disposition'))
        if actual_slot != slot_id:
            findings.append((segment_id, 'slot'))
    return tuple(findings)
