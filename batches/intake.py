import sqlite3

from batches.revisions import new_revision
from batches.segments import require_identifier, validate_segments
from batches.store import BatchStore
from batches.timings import validate_timings


def put_batch(
    connection: sqlite3.Connection,
    batch_id: str,
    segments,
    public_segments,
    base_timings,
    changeovers=(),
    *,
    parent_revision_id: str | None = None,
) -> str:
    require_identifier(batch_id, 'batch id')
    ordered_segments, public_order = validate_segments(segments, public_segments)
    bases, extras = validate_timings(ordered_segments, base_timings, changeovers)
    store = BatchStore(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        if parent_revision_id is None:
            try:
                parent = store.load_current(batch_id)
            except LookupError:
                parent = None
        else:
            require_identifier(parent_revision_id, 'parent revision id')
            try:
                parent = store.load_revision(parent_revision_id)
            except LookupError as error:
                raise ValueError('unknown parent revision') from error
        revision = new_revision(batch_id, ordered_segments, public_order, bases, extras, parent)
        store.insert_revision(revision)
    return revision.revision_id
