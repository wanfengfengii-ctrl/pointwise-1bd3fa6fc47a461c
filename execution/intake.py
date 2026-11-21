from dataclasses import dataclass

from analysis.artifacts import PUBLIC_DISPOSITIONS
from batches.segments import require_identifier


@dataclass(frozen=True, slots=True)
class ActualDisposition:
    segment_id: str
    disposition: str


def validate_actuals(plan: tuple[tuple[str, str], ...], records) -> tuple[ActualDisposition, ...]:
    actuals = tuple(records)
    allowed = {segment_id for segment_id, _ in plan}
    seen = set()
    for actual in actuals:
        if not isinstance(actual, ActualDisposition):
            raise ValueError('expected ActualDisposition record')
        segment_id = actual.segment_id
        if type(segment_id) is not str or segment_id not in allowed:
            raise ValueError('actual disposition references a segment outside the plan')
        if segment_id in seen:
            raise ValueError(f'duplicate actual disposition for {segment_id}')
        if actual.disposition not in PUBLIC_DISPOSITIONS:
            raise ValueError(f'invalid actual disposition for {segment_id}')
        seen.add(segment_id)
    return actuals


def validate_work_actuals(
    assignment: tuple[tuple[str, str, str], ...], records,
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(records, (list, tuple)):
        raise ValueError('expected a list or tuple of actual rows')
    assigned = {segment_id for segment_id, _, _ in assignment}
    seen = set()
    actuals = []
    for row in records:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError('expected a segment, disposition and slot triple')
        segment_id, disposition, slot_id = row
        if type(segment_id) is not str or segment_id not in assigned:
            raise ValueError('actual references a segment outside the assignment')
        if segment_id in seen:
            raise ValueError(f'duplicate actual for {segment_id}')
        if disposition not in PUBLIC_DISPOSITIONS:
            raise ValueError(f'invalid actual disposition for {segment_id}')
        require_identifier(slot_id, 'actual slot id')
        seen.add(segment_id)
        actuals.append((segment_id, disposition, slot_id))
    return tuple(actuals)
