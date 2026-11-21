from dataclasses import dataclass

from batches.segments import require_identifier


@dataclass(frozen=True, slots=True)
class BaseTiming:
    timing_id: str
    segment_id: str
    disposition: str
    amount: int
    unit: str = 'work'


@dataclass(frozen=True, slots=True)
class ChangeoverTiming:
    timing_id: str
    start_segment: str
    end_segment: str
    amount: int
    unit: str = 'work'


def _validate_common(timing, known_ids: set[str]) -> None:
    timing_id = require_identifier(timing.timing_id, 'timing id')
    if timing_id in known_ids:
        raise ValueError(f'duplicate timing {timing_id}')
    if type(timing.amount) is not int or timing.amount < 0:
        raise ValueError(f'invalid amount for {timing_id}')
    require_identifier(timing.unit, 'timing unit')
    known_ids.add(timing_id)


def _check_segment(value, known_segments: set[str]) -> None:
    segment_id = require_identifier(value, 'timing segment id')
    if segment_id not in known_segments:
        raise ValueError(f'timing references unknown segment {segment_id}')


def validate_timings(segments, base_timings, changeovers):
    bases = tuple(base_timings)
    extras = tuple(changeovers)
    segment_ids = {segment.segment_id for segment in segments}
    timing_ids: set[str] = set()
    found = set()
    for timing in bases:
        if not isinstance(timing, BaseTiming):
            raise ValueError('expected BaseTiming record')
        _validate_common(timing, timing_ids)
        _check_segment(timing.segment_id, segment_ids)
        if timing.disposition not in ('retest', 'release'):
            raise ValueError('invalid base disposition')
        key = (timing.segment_id, timing.disposition)
        if key in found:
            raise ValueError(f'duplicate base timing for {key}')
        found.add(key)

    if len(found) != 2 * len(segment_ids):
        raise ValueError('both base dispositions require an explicit timing for every segment')
    for timing in extras:
        if not isinstance(timing, ChangeoverTiming):
            raise ValueError('expected ChangeoverTiming record')
        _validate_common(timing, timing_ids)
        _check_segment(timing.start_segment, segment_ids)
        _check_segment(timing.end_segment, segment_ids)
    return bases, extras
