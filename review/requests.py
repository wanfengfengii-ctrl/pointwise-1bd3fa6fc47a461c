from collections.abc import Mapping
from dataclasses import dataclass

from analysis.artifacts import PUBLIC_DISPOSITIONS


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    assignments: tuple[tuple[str, str], ...]


def validate_request(public_segments: tuple[str, ...], requirements) -> ReviewRequest:
    selected = {}
    public = set(public_segments)
    entries = requirements.items() if isinstance(requirements, Mapping) else requirements
    try:
        entries = iter(entries)
    except TypeError as error:
        raise ValueError('expected a sequence of requested dispositions') from error
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('expected a segment and disposition pair')
        segment_id, disposition = entry
        if type(segment_id) is not str or segment_id not in public:
            raise ValueError('request references a nonpublic segment')
        if disposition not in PUBLIC_DISPOSITIONS:
            raise ValueError(f'invalid disposition for {segment_id}')
        if segment_id in selected:
            raise ValueError(f'duplicate request for {segment_id}')
        selected[segment_id] = disposition
    return ReviewRequest(tuple((segment_id, selected[segment_id]) for segment_id in public_segments if segment_id in selected))
