from dataclasses import dataclass

from analysis.artifacts import PUBLIC_DISPOSITIONS


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
