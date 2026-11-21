from dataclasses import replace
import sqlite3
import unittest

from analysis.archive import AnalysisArchive
from analysis.publish import publish_analysis
from batches.intake import put_batch
from batches.segments import Segment
from batches.store import BatchStore
from batches.timings import ChangeoverTiming
from tests.test_workflow import POLICY, initialize_station, put_bridge, zero_bases


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.connection = initialize_station(sqlite3.connect(':memory:'))
        self.addCleanup(self.connection.close)
        self.store = BatchStore(self.connection)
        self.segments = (Segment('A'), Segment('B'))
        self.bases = zero_bases('A', 'B')

    def put(self, batch_id='roll', **kwargs):
        return put_batch(self.connection, batch_id, self.segments, ('B', 'A'), self.bases, **kwargs)

    def test_initial_revision(self):
        revision_id = self.put()
        revision = self.store.load_current('roll')
        self.assertEqual(revision, self.store.load_revision(revision_id))
        self.assertEqual(self.segments, revision.segments)
        self.assertEqual(('A', 'B'), revision.public_segments)
        self.assertEqual(self.bases, revision.base_timings)
        self.assertIsNone(revision.parent_revision_id)
        self.assertFalse(revision.frozen)

    def test_duplicate_segment_rejects_revision(self):
        original = self.put()
        saved = publish_analysis(self.connection, original, POLICY)
        with self.assertRaises(ValueError):
            put_batch(self.connection, 'roll', (Segment('A'), Segment('A')), ('A',), self.bases)
        self.assertEqual(original, self.store.load_current('roll').revision_id)
        self.assertEqual(1, self.connection.execute('SELECT COUNT(*) FROM batch_revisions').fetchone()[0])
        self.assertEqual(saved, AnalysisArchive(self.connection).load_analysis(saved.analysis_id))

    def test_valid_correction(self):
        first = self.put()
        corrected = (replace(self.bases[0], amount=3), *self.bases[1:])
        next_id = put_batch(self.connection, 'roll', self.segments, ('A',), corrected)
        latest = self.store.load_current('roll')
        self.assertNotEqual(first, next_id)
        self.assertEqual((next_id, first, corrected), (latest.revision_id, latest.parent_revision_id, latest.base_timings))
        self.assertEqual(self.bases, self.store.load_revision(first).base_timings)
        branch = self.put(parent_revision_id=first)
        self.assertEqual(first, self.store.load_revision(branch).parent_revision_id)
        self.assertEqual(branch, self.store.load_current('roll').revision_id)

    def test_cross_batch_parent(self):
        first = self.put('first')
        second = self.put('second')
        for parent_id in (first, 'missing-revision'):
            with self.subTest(parent_id=parent_id), self.assertRaises(ValueError):
                self.put('second', parent_revision_id=parent_id)
        self.assertEqual(first, self.store.load_current('first').revision_id)
        self.assertEqual(second, self.store.load_current('second').revision_id)
        self.assertEqual(2, self.connection.execute('SELECT COUNT(*) FROM batch_revisions').fetchone()[0])
        valid = self.put('second', parent_revision_id=second)
        self.assertEqual(second, self.store.load_revision(valid).parent_revision_id)

    def test_freeze_original(self):
        first = put_bridge(self.connection)
        analysis = publish_analysis(self.connection, first, POLICY)
        second = put_bridge(self.connection, linked=False)
        old = self.store.load_revision(first)
        self.assertTrue(old.frozen)
        self.assertEqual(['edge-ah', 'edge-hb'], [entry.timing_id for entry in old.changeovers])
        self.assertEqual(second, self.store.load_current('bridge').revision_id)
        self.assertFalse(self.store.load_revision(second).frozen)
        self.assertEqual(analysis, AnalysisArchive(self.connection).load_analysis(analysis.analysis_id))

    def test_invalid_references_and_amounts_reject_all_input(self):
        cases = (
            (('unknown',), self.bases, ()),
            (('A', 'A'), self.bases, ()),
            (('A',), self.bases[:-1], ()),
            (('A',), (replace(self.bases[0], amount=None), *self.bases[1:]), ()),
            (('A',), (replace(self.bases[0], amount=-1), *self.bases[1:]), ()),
            (('A',), (replace(self.bases[0], amount=True), *self.bases[1:]), ()),
            (('A',), self.bases, (ChangeoverTiming('edge', 'A', 'unknown', 1),)),
            (('A',), self.bases, (ChangeoverTiming(self.bases[0].timing_id, 'A', 'B', 1),)),
        )
        for public, bases, extras in cases:
            with self.subTest(public=public, bases=bases, extras=extras), self.assertRaises(ValueError):
                put_batch(self.connection, 'invalid', self.segments, public, bases, extras)
        with self.assertRaises(LookupError):
            self.store.load_current('invalid')
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM batch_revisions').fetchone()[0])
