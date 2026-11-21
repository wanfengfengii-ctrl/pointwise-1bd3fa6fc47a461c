from contextlib import closing
from itertools import product
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from analysis.archive import AnalysisArchive
from analysis.artifacts import decode_artifact
from analysis.publish import publish_analysis
from batches.store import BatchStore
from tests.test_workflow import POLICY, initialize_station, put_bridge, refuse_commit


def admitted_rows(artifact):
    evidence = artifact.evidence
    rows = set()
    for bits in product((0, 1), repeat=len(artifact.public_segments)):
        values = dict(zip(artifact.public_segments, bits))
        if any(values[segment_id] != 1 for segment_id in evidence.forced_retest):
            continue
        if any(values[segment_id] != 0 for segment_id in evidence.forced_release):
            continue
        if any(values[start] > values[end] for start, end in evidence.implications):
            continue
        rows.add(bits)
    return rows


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.connection = initialize_station(sqlite3.connect(':memory:'))
        self.addCleanup(self.connection.close)
        self.archive = AnalysisArchive(self.connection)

    def test_private_bridge_projection(self):
        revision = put_bridge(self.connection)
        saved = publish_analysis(self.connection, revision, POLICY)
        artifact = decode_artifact(saved.artifact)
        self.assertEqual(0, artifact.minimum_work)
        self.assertEqual(('A', 'B'), artifact.public_segments)
        self.assertEqual({(0, 0), (0, 1), (1, 1)}, admitted_rows(artifact))
        for private in ('H-internal', 'edge-ah', 'edge-hb', 'base-A-release', 'capacities'):
            self.assertNotIn(private, saved.artifact)
        self.assertEqual(saved, self.archive.load_analysis(saved.analysis_id))

    def test_independent_control(self):
        saved = publish_analysis(self.connection, put_bridge(self.connection, linked=False), POLICY)
        artifact = decode_artifact(saved.artifact)
        self.assertEqual(0, artifact.minimum_work)
        self.assertEqual(set(product((0, 1), repeat=2)), admitted_rows(artifact))

    def test_empty_public(self):
        saved = publish_analysis(self.connection, put_bridge(self.connection, public=()), POLICY)
        artifact = decode_artifact(saved.artifact)
        self.assertEqual((), artifact.public_segments)
        self.assertEqual({()}, admitted_rows(artifact))
        self.assertEqual(0, artifact.minimum_work)

    def test_failed_publish_retains_previous(self):
        old_id = put_bridge(self.connection)
        old = publish_analysis(self.connection, old_id, POLICY)
        candidate = put_bridge(self.connection, linked=False)
        with refuse_commit(self.connection), self.assertRaises(sqlite3.DatabaseError):
            publish_analysis(self.connection, candidate, POLICY)
        self.assertEqual(old, self.archive.load_analysis(old.analysis_id))
        rows = self.connection.execute('SELECT analysis_id FROM analysis_archive').fetchall()
        self.assertEqual([(old.analysis_id,)], rows)
        self.assertTrue(BatchStore(self.connection).load_revision(old_id).frozen)
        self.assertFalse(BatchStore(self.connection).load_revision(candidate).frozen)

    def test_freeze_atomic(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'station.db')
            with closing(initialize_station(sqlite3.connect(path))) as station:
                candidate = put_bridge(station)
                with refuse_commit(station), self.assertRaises(sqlite3.DatabaseError):
                    publish_analysis(station, candidate, POLICY)
                self.assertFalse(station.in_transaction)
            with closing(sqlite3.connect(path)) as reopened:
                self.assertFalse(BatchStore(reopened).load_revision(candidate).frozen)
                self.assertEqual([], reopened.execute('SELECT analysis_id FROM analysis_archive').fetchall())
                saved = publish_analysis(initialize_station(reopened), candidate, POLICY)
                self.assertEqual(saved, AnalysisArchive(reopened).load_analysis(saved.analysis_id))

    def test_repeat_init_station(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'station.db')
            with closing(initialize_station(sqlite3.connect(path))) as station:
                first = put_bridge(station)
                saved = publish_analysis(station, first, POLICY)
                latest = put_bridge(station, linked=False)
                initialize_station(station)
            with closing(initialize_station(sqlite3.connect(path))) as reopened:
                self.assertEqual(latest, BatchStore(reopened).load_current('bridge').revision_id)
                self.assertTrue(BatchStore(reopened).load_revision(first).frozen)
                self.assertEqual(saved, AnalysisArchive(reopened).load_analysis(saved.analysis_id))
