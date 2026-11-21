from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Segment:
    segment_id: str


def require_identifier(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError(f'invalid {label}')
    return value


def public_segment_ids(segments, public_ids) -> tuple[str, ...]:
    selected = set(public_ids)
    return tuple(segment.segment_id for segment in segments if segment.segment_id in selected)


def validate_segments(segments, public_ids) -> tuple[tuple[Segment, ...], tuple[str, ...]]:
    records = tuple(segments)
    known = set()
    if not records:
        raise ValueError('a batch requires at least one segment')
    for segment in records:
        if not isinstance(segment, Segment):
            raise ValueError('expected Segment record')
        segment_id = require_identifier(segment.segment_id, 'segment id')
        if segment_id in known:
            raise ValueError(f'duplicate segment {segment_id}')
        known.add(segment_id)

    selected = set()
    for raw_id in public_ids:
        segment_id = require_identifier(raw_id, 'public segment id')
        if segment_id not in known or segment_id in selected:
            raise ValueError(f'invalid public segment {segment_id}')
        selected.add(segment_id)
    return records, public_segment_ids(records, selected)
