import json
import sqlite3
from dataclasses import asdict

from batches.revisions import BatchRevision
from batches.segments import Segment
from batches.timings import BaseTiming, ChangeoverTiming


_STATION_ID = 0x53545250
_REVISION_FIELDS = 'revision_id, batch_id, parent_revision_id, frozen, body'


def _decode_revision(row) -> BatchRevision:
    revision_id, batch_id, parent_id, frozen, encoded = row
    body = json.loads(encoded)
    return BatchRevision(
        revision_id=revision_id,
        batch_id=batch_id,
        parent_revision_id=parent_id,
        segments=tuple(Segment(segment_id) for segment_id in body['segments']),
        public_segments=tuple(body['public_segments']),
        base_timings=tuple(BaseTiming(**item) for item in body['base_timings']),
        changeovers=tuple(ChangeoverTiming(**item) for item in body['changeovers']),
        frozen=bool(frozen),
    )


class BatchStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        conn = self.connection
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('BEGIN IMMEDIATE')
        with conn:
            application = conn.execute('PRAGMA application_id').fetchone()[0]
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            fresh = (application, version) == (0, 0)
            if fresh:
                existing = conn.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
                if existing is not None:
                    raise ValueError('unrecognized station database')
            elif (application, version) != (_STATION_ID, 1):
                raise ValueError('incompatible station database')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS batch_revisions (
                    revision_id TEXT PRIMARY KEY NOT NULL,
                    batch_id TEXT NOT NULL,
                    parent_revision_id TEXT REFERENCES batch_revisions(revision_id),
                    frozen INTEGER NOT NULL CHECK (frozen IN (0, 1)),
                    body TEXT NOT NULL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS batch_current (
                    batch_id TEXT PRIMARY KEY NOT NULL,
                    revision_id TEXT NOT NULL REFERENCES batch_revisions(revision_id)
                )
            ''')
            conn.execute(f'SELECT {_REVISION_FIELDS} FROM batch_revisions LIMIT 0')
            conn.execute('SELECT batch_id, revision_id FROM batch_current LIMIT 0')
            if fresh:
                conn.execute(f'PRAGMA application_id = {_STATION_ID}')
                conn.execute('PRAGMA user_version = 1')

    def load_revision(self, revision_id: str) -> BatchRevision:
        row = self.connection.execute(
            f'SELECT {_REVISION_FIELDS} FROM batch_revisions WHERE revision_id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown batch revision {revision_id}')
        return _decode_revision(row)

    def load_current(self, batch_id: str) -> BatchRevision:
        current = self.connection.execute(
            'SELECT revision_id FROM batch_current WHERE batch_id = ?', (batch_id,),
        ).fetchone()
        if current is None:
            raise LookupError(f'unknown batch {batch_id}')
        return self.load_revision(current[0])

    def insert_revision(self, revision: BatchRevision) -> None:
        body = json.dumps({
            'segments': [segment.segment_id for segment in revision.segments],
            'public_segments': revision.public_segments,
            'base_timings': [asdict(timing) for timing in revision.base_timings],
            'changeovers': [asdict(timing) for timing in revision.changeovers],
        }, separators=(',', ':'))
        self.connection.execute(
            'INSERT INTO batch_revisions VALUES (?, ?, ?, ?, ?)',
            (revision.revision_id, revision.batch_id, revision.parent_revision_id, int(revision.frozen), body),
        )
        self.connection.execute('''
            INSERT INTO batch_current (batch_id, revision_id) VALUES (?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET revision_id = excluded.revision_id
        ''', (revision.batch_id, revision.revision_id))

    def save_frozen_revision(self, revision: BatchRevision) -> None:
        if not revision.frozen:
            raise ValueError('freeze the revision before saving it')
        updated = self.connection.execute(
            'UPDATE batch_revisions SET frozen = 1 WHERE revision_id = ?', (revision.revision_id,),
        )
        if updated.rowcount != 1:
            raise LookupError(f'unknown batch revision {revision.revision_id}')
