from collections import defaultdict, deque

from analysis.artifacts import AnalysisArtifact, PUBLIC_DISPOSITIONS
from batches.segments import require_identifier
from review.requests import ReviewRequest


def validate_open_slots(open_slots) -> tuple[str, ...]:
    if not isinstance(open_slots, (list, tuple)):
        raise ValueError('expected a list or tuple of open slot ids')
    slots = []
    seen = set()
    for raw in open_slots:
        slot_id = require_identifier(raw, 'slot id')
        if slot_id in seen:
            raise ValueError(f'duplicate open slot {slot_id}')
        seen.add(slot_id)
        slots.append(slot_id)
    return tuple(slots)


def validate_compatibility(
    public_segments: tuple[str, ...], open_slots: tuple[str, ...], compatibility,
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(compatibility, (list, tuple)):
        raise ValueError('expected a list or tuple of compatibility rows')
    public = set(public_segments)
    opened = set(open_slots)
    rows = []
    seen = set()
    for raw in compatibility:
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            raise ValueError('expected a segment, disposition and slot triple')
        segment_id, disposition, slot_id = raw
        if type(segment_id) is not str or segment_id not in public:
            raise ValueError('compatibility references a nonpublic segment')
        if disposition not in PUBLIC_DISPOSITIONS:
            raise ValueError(f'invalid compatibility disposition for {segment_id}')
        if type(slot_id) is not str or slot_id not in opened:
            raise ValueError('compatibility references a slot outside the open list')
        row = (segment_id, disposition, slot_id)
        if row in seen:
            raise ValueError('duplicate compatibility row')
        seen.add(row)
        rows.append(row)
    return tuple(rows)


def assign_slots(
    analysis: AnalysisArtifact,
    request: ReviewRequest,
    open_slots: tuple[str, ...],
    compatibility: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[str, str, str], ...] | None:
    evidence = analysis.evidence
    requested = dict(request.assignments)
    must_retest = set(evidence.forced_retest)
    must_retest.update(
        segment_id for segment_id, disposition in requested.items() if disposition == 'retest'
    )
    successors = defaultdict(list)
    for start, end in evidence.implications:
        successors[start].append(end)
    queue = deque(must_retest)
    while queue:
        segment_id = queue.popleft()
        for implied in successors[segment_id]:
            if implied not in must_retest:
                must_retest.add(implied)
                queue.append(implied)
    must_release = set(evidence.forced_release)
    must_release.update(
        segment_id for segment_id, disposition in requested.items() if disposition == 'release'
    )
    if must_retest.intersection(must_release):
        return None

    candidates = defaultdict(list)
    for segment_id, disposition, slot_id in compatibility:
        candidates[(segment_id, disposition)].append(slot_id)

    public = analysis.public_segments
    implications = evidence.implications
    dispositions: dict[str, str] = {}
    slots: dict[str, str] = {}
    used = set()

    def consistent() -> bool:
        return not any(
            dispositions.get(start) == 'retest' and dispositions.get(end) == 'release'
            for start, end in implications
        )

    def search(index: int) -> bool:
        if index == len(public):
            return True
        segment_id = public[index]
        if segment_id in must_retest:
            choices = ('retest',)
        elif segment_id in must_release:
            choices = ('release',)
        else:
            choices = ('release', 'retest')
        for disposition in choices:
            for slot_id in candidates.get((segment_id, disposition), ()):
                if slot_id in used:
                    continue
                dispositions[segment_id] = disposition
                slots[segment_id] = slot_id
                used.add(slot_id)
                if consistent() and search(index + 1):
                    return True
                used.discard(slot_id)
                del dispositions[segment_id]
                del slots[segment_id]
        return False

    if not search(0):
        return None
    return tuple((segment_id, dispositions[segment_id], slots[segment_id]) for segment_id in public)
