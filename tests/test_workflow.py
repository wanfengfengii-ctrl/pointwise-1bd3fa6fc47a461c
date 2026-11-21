from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from analysis.archive import AnalysisArchive
from analysis.publish import publish_analysis
from batches.intake import put_batch
from batches.segments import Segment
from batches.store import BatchStore
from batches.timings import BaseTiming, ChangeoverTiming
from execution.store import ExecutionStore
from review.decisions import review_plan
from review.store import ReviewStore


POLICY = 'line-v1'


def initialize_station(connection):
    BatchStore(connection).initialize()
    AnalysisArchive(connection).initialize()
    return connection


def initialize_offline(connection):
    ReviewStore(connection).initialize()
    ExecutionStore(connection).initialize()
    return connection


def zero_bases(*segment_ids):
    return tuple(
        BaseTiming(f'base-{segment_id}-{disposition}', segment_id, disposition, 0)
        for segment_id in segment_ids
        for disposition in ('release', 'retest')
    )


def put_bridge(connection, batch_id='bridge', *, linked=True, public=('A', 'B')):
    ids = ('A', 'H-internal', 'B')
    extras = (
        ChangeoverTiming('edge-ah', 'A', 'H-internal', 1),
        ChangeoverTiming('edge-hb', 'H-internal', 'B', 1),
    ) if linked else ()
    return put_batch(connection, batch_id, tuple(Segment(part) for part in ids), public, zero_bases(*ids), extras)


def external_fixture(*, analysis_id='external-bridge', linked=True):
    return json.dumps({
        'version': 1,
        'analysis_id': analysis_id,
        'batch_id': 'external-batch',
        'revision_id': 'external-revision',
        'policy_version': 'external-policy',
        'minimum_work': 0,
        'public_segments': ['A', 'B'],
        'evidence': {
            'forced_retest': [], 'forced_release': [],
            'implications': [['A', 'B']] if linked else [],
        },
    })


@contextmanager
def refuse_commit(connection):
    denied = False

    def authorize(action, detail, _other, _database, _source):
        nonlocal denied
        if action == sqlite3.SQLITE_TRANSACTION and detail == 'COMMIT':
            denied = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    try:
        yield
    finally:
        connection.set_authorizer(None)
    if not denied:
        raise AssertionError('the operation did not reach its SQLite commit')


class WorkflowTests(unittest.TestCase):
    def test_offline_joint_handoff(self):
        with TemporaryDirectory() as directory:
            with closing(initialize_station(sqlite3.connect(Path(directory, 'station.db')))) as station:
                bridge = publish_analysis(station, put_bridge(station), POLICY)
                control = publish_analysis(station, put_bridge(station, 'control', linked=False), POLICY)
            self.assertEqual((0, 0), (bridge.minimum_work, control.minimum_work))
            self.assertNotIn('H-internal', bridge.artifact)
            self.assertNotIn('edge-ah', bridge.artifact)
            with closing(initialize_offline(sqlite3.connect(Path(directory, 'offline.db')))) as offline:
                request = {'A': 'retest', 'B': 'release'}
                blocked = review_plan(offline, request, artifact=bridge.artifact)
                self.assertEqual('infeasible', blocked.status, 'JOINT_REQUEST_FALSE_APPROVAL')
                self.assertIsNone(blocked.plan)
                allowed = review_plan(offline, request, artifact=control.artifact)
                self.assertEqual('approved', allowed.status)
                self.assertEqual((('A', 'retest'), ('B', 'release')), allowed.plan)
                reverse = review_plan(offline, {'A': 'release', 'B': 'retest'}, analysis_id=bridge.analysis_id)
                self.assertEqual((('A', 'release'), ('B', 'retest')), reverse.plan)
                completed = review_plan(offline, {'A': 'retest'}, analysis_id=bridge.analysis_id)
                self.assertEqual((('A', 'retest'), ('B', 'retest')), completed.plan)
