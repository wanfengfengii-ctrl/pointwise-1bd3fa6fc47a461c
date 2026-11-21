from dataclasses import replace
import sqlite3
import unittest

from analysis.publish import publish_analysis
from batches.intake import put_batch
from batches.segments import Segment
from batches.store import BatchStore
from batches.timings import BaseTiming, ChangeoverTiming
from costs.ledger import score_batch
from tests.test_workflow import POLICY, initialize_station


class CostTests(unittest.TestCase):
    def setUp(self):
        self.connection = initialize_station(sqlite3.connect(':memory:'))
        self.addCleanup(self.connection.close)
        self.segments = (Segment('A'), Segment('B'))
        self.base = (
            BaseTiming('a-r', 'A', 'retest', 1), BaseTiming('a-l', 'A', 'release', 1),
            BaseTiming('b-r', 'B', 'retest', 2), BaseTiming('b-l', 'B', 'release', 2),
        )
        self.extras = (
            ChangeoverTiming('first', 'A', 'B', 2), ChangeoverTiming('second', 'A', 'B', 4),
            ChangeoverTiming('reverse', 'B', 'A', 8),
        )
        self.revision = self.put(self.base, self.extras)

    def put(self, base, extras):
        return put_batch(self.connection, 'roll', self.segments, ('A', 'B'), base, extras)

    def test_two_parallel_charges(self):
        score = score_batch(self.connection, self.revision, POLICY, {'A': 'retest', 'B': 'release'})
        self.assertEqual((3, 6, 9), (score.base_total, score.changeover_total, score.total_work))
        self.assertEqual([('a-r', 1), ('b-l', 2), ('first', 2), ('second', 4)], [
            (entry.timing_id, entry.work) for entry in score.entries
        ])

    def test_direction_swap(self):
        forward = score_batch(self.connection, self.revision, POLICY, {'A': 'retest', 'B': 'release'})
        reverse = score_batch(self.connection, self.revision, POLICY, {'A': 'release', 'B': 'retest'})
        none = score_batch(self.connection, self.revision, POLICY, {'A': 'release', 'B': 'release'})
        self.assertEqual((9, 11, 3), (forward.total_work, reverse.total_work, none.total_work))
        self.assertEqual(['reverse'], [entry.timing_id for entry in reverse.entries if entry.kind == 'changeover'])
        self.assertEqual(0, none.changeover_total)

    def test_unit_conversion(self):
        bases = tuple(replace(timing, amount=1, unit='tick') if timing.segment_id == 'B' else timing for timing in self.base)
        extras = tuple(replace(timing, amount=timing.amount // 2, unit='tick') for timing in self.extras)
        converted = self.put(bases, extras)
        plan = {'A': 'retest', 'B': 'release'}
        original_score = score_batch(self.connection, self.revision, POLICY, plan)
        converted_score = score_batch(self.connection, converted, POLICY, plan)
        self.assertEqual(9, converted_score.total_work)
        self.assertEqual(original_score.entries, converted_score.entries)
        self.assertEqual((converted, POLICY), (converted_score.revision_id, converted_score.policy_version))
        bench = score_batch(self.connection, converted, 'bench-v1', plan)
        self.assertEqual(13, bench.total_work)

    def test_invalid_score(self):
        for plan in ({'A': 'retest'}, {'A': 'retest', 'B': 'hold'}, {'A': 'retest', 'B': 'release', 'X': 'retest'}):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                score_batch(self.connection, self.revision, POLICY, plan)
        full = {'A': 'retest', 'B': 'release'}
        with self.assertRaises(ValueError):
            score_batch(self.connection, self.revision, 'unknown', full)
        unknown_unit = self.put(self.base, (replace(self.extras[0], unit='unknown'),))
        with self.assertRaises(ValueError):
            score_batch(self.connection, unknown_unit, POLICY, full)
        with self.assertRaises(ValueError):
            publish_analysis(self.connection, unknown_unit, POLICY)
        self.assertFalse(BatchStore(self.connection).load_revision(unknown_unit).frozen)
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM analysis_archive').fetchone()[0])

    def test_exact_integer_work_above_sqlite_integer_range(self):
        work = 10 ** 35
        bases = tuple(replace(timing, amount=work) for timing in self.base)
        revision = self.put(bases, self.extras)
        self.assertEqual(2 * work + 6, score_batch(
            self.connection, revision, POLICY, {'A': 'retest', 'B': 'release'},
        ).total_work)
        self.assertEqual(2 * work, publish_analysis(self.connection, revision, POLICY).minimum_work)
