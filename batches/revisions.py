from dataclasses import dataclass, replace
from uuid import uuid4

from batches.segments import Segment
from batches.timings import BaseTiming, ChangeoverTiming


@dataclass(frozen=True, slots=True)
class BatchRevision:
    revision_id: str
    batch_id: str
    parent_revision_id: str | None
    segments: tuple[Segment, ...]
    public_segments: tuple[str, ...]
    base_timings: tuple[BaseTiming, ...]
    changeovers: tuple[ChangeoverTiming, ...]
    frozen: bool = False

    def freeze(self) -> 'BatchRevision':
        return self if self.frozen else replace(self, frozen=True)


def new_revision(batch_id, segments, public_segments, base_timings, changeovers, parent=None) -> BatchRevision:
    if parent is not None and parent.batch_id != batch_id:
        raise ValueError('parent revision belongs to a different batch')
    return BatchRevision(
        revision_id=f'revision-{uuid4().hex}',
        batch_id=batch_id,
        parent_revision_id=parent.revision_id if parent is not None else None,
        segments=segments,
        public_segments=public_segments,
        base_timings=base_timings,
        changeovers=changeovers,
    )
