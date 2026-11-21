from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from analysis.publish import publish_analysis
from execution.closeout import close_execution, close_work_order
from execution.intake import ActualDisposition
from review.decisions import issue_work_order, review_plan
from review.imports import accept_analysis
from review.reports import read_result
from tests.test_workflow import (
    POLICY, initialize_offline, initialize_station, put_bridge, put_reassign, refuse_commit,
)


def slot_case(name):
    path = Path(__file__).resolve().parents[1] / 'samples' / 'slot_shift.json'
    return json.loads(path.read_text(encoding='utf-8'))[name]


class WorkOrderTests(unittest.TestCase):
    def setUp(self):
        self.station = initialize_station(sqlite3.connect(':memory:'))
        self.addCleanup(self.station.close)
        self.saved = publish_analysis(self.station, put_bridge(self.station), POLICY)
        self.connection = initialize_offline(sqlite3.connect(':memory:'))
        self.addCleanup(self.connection.close)
        self.accepted = accept_analysis(self.connection, self.saved.artifact)
        self.shared = slot_case('shared')

    def issue(self, requirements, case=None, *, analysis_id=None):
        case = self.shared if case is None else case
        return issue_work_order(
            self.connection, requirements, case['open_slots'], case['compatibility'],
            analysis_id=self.accepted.analysis_id if analysis_id is None else analysis_id,
        )

    def test_shared_issue_close_and_collect(self):
        order = self.issue({})
        self.assertEqual('approved', order.status)
        self.assertEqual((('A', 'release', 'L1'), ('B', 'retest', 'R1')), order.assignment)
        self.assertEqual(tuple(self.shared['open_slots']), order.open_slots)
        self.assertEqual(tuple(map(tuple, self.shared['compatibility'])), order.compatibility)
        self.assertEqual((), order.request.assignments)
        self.assertEqual(self.accepted.analysis_id, order.analysis_id)
        closed = close_work_order(self.connection, order.report_id, self.shared['actuals'])
        self.assertEqual((('A', 'release', 'L9'),), closed.actuals)
        self.assertEqual((('A', 'slot'), ('B', 'missing')), closed.findings)
        self.assertEqual(order.report_id, closed.report_id)
        self.assertEqual(closed, read_result(self.connection, closed.closeout_id, report_id=order.report_id))
        self.assertEqual(order, read_result(self.connection, order.report_id))

    def test_shared_retest_contention_is_infeasible(self):
        order = self.issue({'A': 'retest'})
        self.assertEqual('infeasible', order.status)
        self.assertIsNone(order.assignment)
        self.assertEqual(order, read_result(self.connection, order.report_id))
        with self.assertRaises(ValueError):
            close_work_order(self.connection, order.report_id, ())

    def test_shared_release_contention_is_infeasible(self):
        order = self.issue({'A': 'release', 'B': 'release'})
        self.assertEqual('infeasible', order.status)
        self.assertIsNone(order.assignment)

    def test_requested_partial_assignment(self):
        order = self.issue({'B': 'retest'})
        self.assertEqual('approved', order.status)
        self.assertEqual((('B', 'retest'),), order.request.assignments)
        self.assertEqual((('A', 'release', 'L1'), ('B', 'retest', 'R1')), order.assignment)

    def test_alternate_slot_choice_and_deviation(self):
        case = slot_case('alternate')
        order = self.issue({}, case)
        self.assertEqual('approved', order.status)
        assigned = {segment: (disposition, slot) for segment, disposition, slot in order.assignment}
        self.assertEqual(('retest', 'R1'), assigned['B'])
        self.assertEqual('release', assigned['A'][0])
        self.assertIn(assigned['A'][1], ('L1', 'L2'))
        other = 'L2' if assigned['A'][1] == 'L1' else 'L1'
        closed = close_work_order(self.connection, order.report_id, [('A', 'release', other)])
        self.assertEqual((('A', 'slot'), ('B', 'missing')), closed.findings)
        both = close_work_order(self.connection, order.report_id, [['A', 'retest', other]])
        self.assertEqual((('A', 'disposition'), ('A', 'slot'), ('B', 'missing')), both.findings)
        self.assertNotEqual(closed.closeout_id, both.closeout_id)
        self.assertEqual(both, read_result(self.connection, both.closeout_id, report_id=order.report_id))

    def test_actual_slot_outside_open_list_and_shared_slot(self):
        order = self.issue({})
        closed = close_work_order(self.connection, order.report_id, [('A', 'release', 'L9'), ('B', 'retest', 'L9')])
        self.assertEqual((('A', 'release', 'L9'), ('B', 'retest', 'L9')), closed.actuals)
        self.assertEqual((('A', 'slot'), ('B', 'slot')), closed.findings)
        exact = close_work_order(self.connection, order.report_id, [('A', 'release', 'L1'), ('B', 'retest', 'R1')])
        self.assertEqual((), exact.findings)

    def test_reassign_unique_assignment_and_withdrawn_slot(self):
        saved = publish_analysis(self.station, put_reassign(self.station), POLICY)
        accepted = accept_analysis(self.connection, saved.artifact)
        self.assertEqual(0, saved.minimum_work)
        self.assertEqual(('C', 'A', 'B'), accepted.public_segments)
        case = slot_case('reassign')
        order = self.issue({}, case, analysis_id=accepted.analysis_id)
        self.assertEqual('approved', order.status)
        self.assertEqual(
            (('C', 'release', 'L2'), ('A', 'release', 'L1'), ('B', 'retest', 'R1')),
            order.assignment,
        )
        slots = [slot for slot in case['open_slots'] if slot != 'L2']
        compat = [row for row in case['compatibility'] if row[2] != 'L2']
        withdrawn = issue_work_order(self.connection, {}, slots, compat, analysis_id=accepted.analysis_id)
        self.assertEqual('infeasible', withdrawn.status)
        self.assertIsNone(withdrawn.assignment)
        self.assertEqual(withdrawn, read_result(self.connection, withdrawn.report_id))

    def test_empty_public_segments(self):
        saved = publish_analysis(self.station, put_bridge(self.station, public=()), POLICY)
        accepted = accept_analysis(self.connection, saved.artifact)
        order = issue_work_order(self.connection, {}, (), (), analysis_id=accepted.analysis_id)
        self.assertEqual('approved', order.status)
        self.assertEqual((), order.assignment)
        closed = close_work_order(self.connection, order.report_id, ())
        self.assertEqual((), closed.actuals)
        self.assertEqual((), closed.findings)
        with self.assertRaises(ValueError):
            close_work_order(self.connection, order.report_id, [('A', 'release', 'L1')])

    def test_invalid_issue_inputs(self):
        slots = self.shared['open_slots']
        compat = self.shared['compatibility']
        for requirements in ({'H-internal': 'release'}, {'A': 'hold'}, [('A', 'release'), ('A', 'retest')], 'A'):
            with self.subTest(requirements=requirements), self.assertRaises(ValueError):
                self.issue(requirements)
        for bad_slots in (['L1', 'L1'], [''], [' L1'], ['L1 '], ['L\n1'], [None], [7], 'L1', [['L1']]):
            with self.subTest(open_slots=bad_slots), self.assertRaises(ValueError):
                issue_work_order(self.connection, {}, bad_slots, compat, analysis_id=self.accepted.analysis_id)
        bad_compat = (
            [['H-internal', 'release', 'L1']],
            [['A', 'hold', 'L1']],
            [['A', 'release', 'L9']],
            [['A', 'release', 'L1'], ['A', 'release', 'L1']],
            [['A', 'release']],
            [['A', 'release', 'L1', 'extra']],
            ['A release L1'],
            'A-release-L1',
            [[None, 'release', 'L1']],
        )
        for bad in bad_compat:
            with self.subTest(compatibility=bad), self.assertRaises(ValueError):
                issue_work_order(self.connection, {}, slots, bad, analysis_id=self.accepted.analysis_id)
        for bad_id in (None, '', 7):
            with self.subTest(analysis_id=bad_id), self.assertRaises(ValueError):
                issue_work_order(self.connection, {}, slots, compat, analysis_id=bad_id)
        with self.assertRaises(LookupError):
            issue_work_order(self.connection, {}, slots, compat, analysis_id='analysis-absent')
        count = self.connection.execute('SELECT COUNT(*) FROM work_order_reports').fetchone()[0]
        self.assertEqual(0, count)

    def test_invalid_close_inputs(self):
        order = self.issue({})
        bad_actuals = (
            'A-release-L1',
            (['A', 'release', 'L1'], ['A', 'retest', 'R1']),
            (['C', 'release', 'L1'],),
            (['A', 'hold', 'L1'],),
            (['A', 'release', ''],),
            (['A', 'release', ' L1'],),
            (['A', 'release'],),
            (['A', 'release', 'L1', 'x'],),
            ('A-release-L1',),
            ((None, 'release', 'L1'),),
        )
        for actuals in bad_actuals:
            with self.subTest(actuals=actuals), self.assertRaises(ValueError):
                close_work_order(self.connection, order.report_id, actuals)
        count = self.connection.execute('SELECT COUNT(*) FROM work_order_closeouts').fetchone()[0]
        self.assertEqual(0, count)

    def test_closeout_entries_are_not_interchangeable(self):
        order = self.issue({})
        decision = review_plan(self.connection, {'A': 'retest'}, analysis_id=self.accepted.analysis_id)
        self.assertEqual('approved', decision.status)
        with self.assertRaises(ValueError):
            close_work_order(self.connection, decision.report_id, ())
        with self.assertRaises(ValueError):
            close_execution(self.connection, order.report_id, (ActualDisposition('A', 'retest'),))
        for entry in (close_work_order, close_execution):
            with self.subTest(entry=entry), self.assertRaises(LookupError):
                entry(self.connection, 'report-absent', ())
        settled = close_execution(self.connection, decision.report_id, (ActualDisposition('A', 'retest'),))
        self.assertEqual(decision.report_id, settled.report_id)

    def test_read_result_dispatch(self):
        order = self.issue({})
        closed = close_work_order(self.connection, order.report_id, self.shared['actuals'])
        self.assertEqual(order, read_result(self.connection, order.report_id))
        self.assertEqual(closed, read_result(self.connection, closed.closeout_id))
        other = self.issue({})
        with self.assertRaises(LookupError):
            read_result(self.connection, closed.closeout_id, report_id=other.report_id)
        with self.assertRaises(ValueError):
            read_result(self.connection, order.report_id, report_id=order.report_id)
        for bad_id in ('', None, 5):
            with self.subTest(result_id=bad_id), self.assertRaises(ValueError):
                read_result(self.connection, bad_id)
        for missing in ('report-absent', 'closeout-absent'):
            with self.subTest(result_id=missing), self.assertRaises(LookupError):
                read_result(self.connection, missing)

    def test_reopen_reads_back_stored_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'offline.db')
            with closing(initialize_offline(sqlite3.connect(path))) as offline:
                accepted = accept_analysis(offline, self.saved.artifact)
                order = issue_work_order(
                    offline, {'B': 'retest'}, self.shared['open_slots'], self.shared['compatibility'],
                    analysis_id=accepted.analysis_id,
                )
                blocked = issue_work_order(
                    offline, {'A': 'retest'}, self.shared['open_slots'], self.shared['compatibility'],
                    analysis_id=accepted.analysis_id,
                )
                closed = close_work_order(offline, order.report_id, self.shared['actuals'])
            with closing(initialize_offline(sqlite3.connect(path))) as reopened:
                self.assertEqual(order, read_result(reopened, order.report_id))
                self.assertEqual(blocked, read_result(reopened, blocked.report_id))
                self.assertEqual(closed, read_result(reopened, closed.closeout_id, report_id=order.report_id))
                self.assertEqual((('A', 'release', 'L9'),), closed.actuals)

    def test_commit_failure_rolls_back_and_allows_retry(self):
        with refuse_commit(self.connection), self.assertRaises(sqlite3.DatabaseError):
            self.issue({})
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM work_order_reports').fetchone()[0])
        order = self.issue({})
        self.assertEqual('approved', order.status)
        with refuse_commit(self.connection), self.assertRaises(sqlite3.DatabaseError):
            close_work_order(self.connection, order.report_id, self.shared['actuals'])
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM work_order_closeouts').fetchone()[0])
        closed = close_work_order(self.connection, order.report_id, self.shared['actuals'])
        self.assertEqual((('A', 'slot'), ('B', 'missing')), closed.findings)
        self.assertEqual(closed, read_result(self.connection, closed.closeout_id, report_id=order.report_id))

    def test_prior_results_survive_failed_writes(self):
        order = self.issue({})
        closed = close_work_order(self.connection, order.report_id, self.shared['actuals'])
        with self.assertRaises(ValueError):
            self.issue({'H-internal': 'release'})
        with self.assertRaises(ValueError):
            close_work_order(self.connection, order.report_id, [('A', 'hold', 'L1')])
        self.assertEqual(order, read_result(self.connection, order.report_id))
        self.assertEqual(closed, read_result(self.connection, closed.closeout_id))
        self.assertEqual(1, self.connection.execute('SELECT COUNT(*) FROM work_order_reports').fetchone()[0])
        self.assertEqual(1, self.connection.execute('SELECT COUNT(*) FROM work_order_closeouts').fetchone()[0])

    def test_v1_database_upgrades_in_place(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'offline.db')
            with closing(initialize_offline(sqlite3.connect(path))) as offline:
                report = review_plan(offline, {'A': 'retest'}, artifact=self.saved.artifact)
                settled = close_execution(offline, report.report_id, (ActualDisposition('A', 'retest'),))
                offline.execute('DROP TABLE work_order_closeouts')
                offline.execute('DROP TABLE work_order_reports')
                offline.commit()
            with closing(initialize_offline(sqlite3.connect(path))) as reopened:
                self.assertEqual(report, read_result(reopened, report.report_id))
                self.assertEqual(settled, read_result(reopened, settled.closeout_id, report_id=report.report_id))
                accepted = accept_analysis(reopened, self.saved.artifact)
                order = issue_work_order(
                    reopened, {}, self.shared['open_slots'], self.shared['compatibility'],
                    analysis_id=accepted.analysis_id,
                )
                self.assertEqual('approved', order.status)
                closed = close_work_order(reopened, order.report_id, self.shared['actuals'])
                self.assertEqual((('A', 'slot'), ('B', 'missing')), closed.findings)
