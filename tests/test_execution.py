from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from execution.closeout import close_execution
from execution.intake import ActualDisposition
from execution.reconcile import SegmentFinding
from review.decisions import review_plan
from review.reports import read_result
from tests.test_workflow import external_fixture, initialize_offline, refuse_commit


def fixed_work_order(connection):
    fixture = json.loads(external_fixture())
    fixture['public_segments'] = ['A', 'B', 'C']
    fixture['evidence']['forced_retest'] = ['C']
    return review_plan(connection, {'A': 'retest'}, artifact=json.dumps(fixture))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.connection = initialize_offline(sqlite3.connect(':memory:'))
        self.addCleanup(self.connection.close)
        self.order = fixed_work_order(self.connection)
        self.actuals = (ActualDisposition('A', 'retest'), ActualDisposition('B', 'release'))
        self.findings = (
            SegmentFinding('B', 'different', 'retest', 'release'),
            SegmentFinding('C', 'missing', 'retest', None),
        )

    def test_closeout_discrepancy_and_missing(self):
        result = close_execution(self.connection, self.order.report_id, self.actuals)
        self.assertEqual((('A', 'retest'), ('B', 'retest'), ('C', 'retest')), self.order.plan)
        self.assertEqual(self.findings, result.findings)
        self.assertEqual(self.actuals, result.actuals)
        self.assertEqual(result, read_result(self.connection, result.closeout_id, report_id=self.order.report_id))

    def test_shuffled_actuals(self):
        original = close_execution(self.connection, self.order.report_id, self.actuals)
        shuffled = close_execution(self.connection, self.order.report_id, reversed(self.actuals))
        self.assertEqual(self.findings, shuffled.findings)
        self.assertEqual(tuple(reversed(self.actuals)), shuffled.actuals)
        self.assertNotEqual(original.closeout_id, shuffled.closeout_id)
        self.assertEqual(original, read_result(self.connection, original.closeout_id))

    def test_invalid_actuals(self):
        original = close_execution(self.connection, self.order.report_id, self.actuals)
        invalid = (
            (ActualDisposition('unknown', 'release'),),
            (ActualDisposition('B', 'release'), ActualDisposition('B', 'retest')),
            (ActualDisposition('A', 'hold'),),
        )
        for actuals in invalid:
            with self.subTest(actuals=actuals), self.assertRaises(ValueError):
                close_execution(self.connection, self.order.report_id, actuals)
        self.assertEqual(original, read_result(self.connection, original.closeout_id))
        self.assertEqual(1, self.connection.execute('SELECT COUNT(*) FROM execution_closeouts').fetchone()[0])

    def test_empty_actuals(self):
        result = close_execution(self.connection, self.order.report_id, ())
        self.assertEqual(tuple(SegmentFinding(part, 'missing', 'retest', None) for part in ('A', 'B', 'C')), result.findings)

    def test_missing_result(self):
        result = close_execution(self.connection, self.order.report_id, self.actuals)
        other = review_plan(self.connection, {}, analysis_id=self.order.analysis_id)
        for result_id in ('report-absent', 'closeout-absent'):
            with self.subTest(result_id=result_id), self.assertRaises(LookupError):
                read_result(self.connection, result_id)
        with self.assertRaises(LookupError):
            read_result(self.connection, result.closeout_id, report_id=other.report_id)

    def test_repeat_init_closeout(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'offline.db')
            with closing(initialize_offline(sqlite3.connect(path))) as offline:
                order = fixed_work_order(offline)
                result = close_execution(offline, order.report_id, self.actuals)
                initialize_offline(offline)
            with closing(initialize_offline(sqlite3.connect(path))) as reopened:
                self.assertEqual(order, read_result(reopened, order.report_id))
                original = read_result(reopened, result.closeout_id, report_id=order.report_id)
                self.assertEqual(self.actuals, original.actuals)
                self.assertEqual(self.findings, original.findings)

    def test_infeasible_decision_cannot_close(self):
        blocked = review_plan(self.connection, {'A': 'retest', 'B': 'release'}, analysis_id=self.order.analysis_id)
        self.assertEqual('infeasible', blocked.status)
        with self.assertRaises(ValueError):
            close_execution(self.connection, blocked.report_id, ())
        self.assertEqual([], self.connection.execute('SELECT closeout_id FROM execution_closeouts').fetchall())

    def test_rejected_after_success(self):
        original = close_execution(self.connection, self.order.report_id, self.actuals)
        blocked = review_plan(self.connection, {'A': 'retest', 'B': 'release'}, analysis_id=self.order.analysis_id)
        with self.assertRaises(ValueError):
            close_execution(self.connection, blocked.report_id, ())
        self.assertEqual(original, read_result(self.connection, original.closeout_id))
        rows = self.connection.execute('SELECT report_id FROM execution_closeouts').fetchall()
        self.assertEqual([(self.order.report_id,)], rows)

    def test_closeout_commit_failure(self):
        original = close_execution(self.connection, self.order.report_id, self.actuals)
        with refuse_commit(self.connection), self.assertRaises(sqlite3.DatabaseError):
            close_execution(self.connection, self.order.report_id, ())
        rows = self.connection.execute('SELECT closeout_id FROM execution_closeouts').fetchall()
        self.assertEqual([(original.closeout_id,)], rows)
        self.assertEqual(original, read_result(self.connection, original.closeout_id))
