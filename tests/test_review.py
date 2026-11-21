from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from analysis.archive import AnalysisArchive
from analysis.publish import publish_analysis
from review.decisions import review_plan
from review.imports import accept_analysis
from review.reports import read_result
from review.store import ReviewStore
from tests.test_workflow import (
    POLICY, external_fixture, initialize_offline, initialize_station, put_bridge, refuse_commit,
)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.connection = initialize_offline(sqlite3.connect(':memory:'))
        self.addCleanup(self.connection.close)
        self.fixture = external_fixture()
        self.store = ReviewStore(self.connection)

    def test_joint_request_on_independent_fixture(self):
        blocked = review_plan(self.connection, {'A': 'retest', 'B': 'release'}, artifact=self.fixture)
        self.assertEqual('infeasible', blocked.status)
        self.assertIsNone(blocked.plan)
        accepted = review_plan(self.connection, {'A': 'release', 'B': 'retest'}, analysis_id=blocked.analysis_id)
        self.assertEqual('approved', accepted.status)
        self.assertEqual((('A', 'release'), ('B', 'retest')), accepted.plan)
        only_a = review_plan(self.connection, {'A': 'retest'}, analysis_id=blocked.analysis_id)
        self.assertEqual((('A', 'retest'), ('B', 'retest')), only_a.plan)

    def test_invalid_artifact(self):
        wrong_version = json.loads(self.fixture)
        wrong_version['version'] = 2
        unknown_end = json.loads(self.fixture)
        unknown_end['evidence']['implications'] = [['A', 'H-internal']]
        contradiction = json.loads(self.fixture)
        contradiction['evidence']['forced_retest'] = ['A']
        contradiction['evidence']['forced_release'] = ['B']
        unknown_field = json.loads(self.fixture)
        unknown_field['station_timings'] = []
        for invalid in (wrong_version, unknown_end, contradiction, unknown_field):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                review_plan(self.connection, {}, artifact=json.dumps(invalid))
        with self.assertRaises(ValueError):
            accept_analysis(self.connection, self.fixture.replace('"version": 1', '"version": 1, "version": 1'))
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM accepted_analyses').fetchone()[0])

    def test_artifact_id_collision(self):
        first = accept_analysis(self.connection, self.fixture)
        equivalent = json.dumps(json.loads(self.fixture), sort_keys=True, indent=2)
        self.assertEqual(first, accept_analysis(self.connection, equivalent))
        with self.assertRaises(ValueError):
            review_plan(self.connection, {}, artifact=external_fixture(linked=False))
        self.assertEqual(first, self.store.load_analysis(first.analysis_id))
        self.assertEqual(0, self.connection.execute('SELECT COUNT(*) FROM decision_reports').fetchone()[0])

    def test_invalid_request(self):
        invalid = ({'H-internal': 'release'}, {'B': 'hold'}, [('A', 'release'), ('A', 'retest')])
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                review_plan(self.connection, request, artifact=self.fixture)
        with self.assertRaises(ValueError):
            review_plan(self.connection, {}, analysis_id='external-bridge', artifact=self.fixture)
        with self.assertRaises(LookupError):
            self.store.load_analysis('external-bridge')
        valid = review_plan(self.connection, {'A': 'retest', 'B': 'release'}, artifact=self.fixture)
        self.assertEqual('infeasible', valid.status)
        self.assertIsNone(read_result(self.connection, valid.report_id).plan)

    def test_complete_plan_after_source_closes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'station.db')
            night_path = Path(directory, 'offline.db')
            with closing(initialize_station(sqlite3.connect(path))) as station:
                saved = publish_analysis(station, put_bridge(station), POLICY)
            with closing(initialize_offline(sqlite3.connect(night_path))) as offline:
                report = review_plan(offline, {'A': 'retest'}, artifact=saved.artifact)
            self.assertEqual((('A', 'retest'), ('B', 'retest')), report.plan)
            with closing(initialize_station(sqlite3.connect(path))) as station:
                changed = publish_analysis(station, put_bridge(station, linked=False), POLICY)
                self.assertNotEqual(saved.analysis_id, changed.analysis_id)
                self.assertEqual(saved, AnalysisArchive(station).load_analysis(saved.analysis_id))
            with closing(initialize_offline(sqlite3.connect(night_path))) as offline:
                self.assertEqual(report, read_result(offline, report.report_id))
                newer = review_plan(offline, {'A': 'retest'}, artifact=changed.artifact)
                self.assertEqual((('A', 'retest'), ('B', 'release')), newer.plan)
                self.assertEqual(report, read_result(offline, report.report_id))

    def test_empty_request(self):
        report = review_plan(self.connection, [], artifact=self.fixture)
        self.assertEqual((), report.request.assignments)
        self.assertEqual('approved', report.status)
        self.assertEqual((('A', 'release'), ('B', 'release')), report.plan)
        empty = json.loads(self.fixture)
        empty['analysis_id'] = 'external-empty'
        empty['public_segments'] = []
        empty['evidence']['implications'] = []
        empty_report = review_plan(self.connection, {}, artifact=json.dumps(empty))
        self.assertEqual('approved', empty_report.status)
        self.assertEqual((), read_result(self.connection, empty_report.report_id).plan)

    def test_two_reports_same_analysis(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, 'offline.db')
            with closing(initialize_offline(sqlite3.connect(path))) as offline:
                first = review_plan(offline, {'A': 'retest'}, artifact=self.fixture)
                second = review_plan(offline, {'B': 'release'}, analysis_id=first.analysis_id)
            with closing(sqlite3.connect(path)) as reopened:
                self.assertEqual(first, read_result(reopened, first.report_id))
                self.assertEqual(second, read_result(reopened, second.report_id))
                self.assertEqual((('A', 'retest'), ('B', 'retest')), first.plan)
                self.assertEqual((('A', 'release'), ('B', 'release')), second.plan)

    def test_report_commit_failure(self):
        original = review_plan(self.connection, {'A': 'retest'}, artifact=self.fixture)
        for request in ({'A': 'retest'}, {'A': 'retest', 'B': 'release'}):
            with self.subTest(request=request):
                candidate = external_fixture(analysis_id='not-committed')
                with refuse_commit(self.connection), self.assertRaises(sqlite3.DatabaseError):
                    review_plan(self.connection, request, artifact=candidate)
                self.assertFalse(self.connection.in_transaction)
                with self.assertRaises(LookupError):
                    self.store.load_analysis('not-committed')
                self.assertEqual(original, read_result(self.connection, original.report_id))
                self.assertEqual([(original.report_id,)], self.connection.execute('SELECT report_id FROM decision_reports').fetchall())

    def test_repeat_init_offline(self):
        original = review_plan(self.connection, {}, artifact=self.fixture)
        accepted = self.store.load_analysis(original.analysis_id)
        initialize_offline(self.connection)
        self.assertEqual(accepted, self.store.load_analysis(original.analysis_id))
        self.assertEqual(original, read_result(self.connection, original.report_id))
        another = review_plan(self.connection, {'A': 'retest'}, analysis_id=original.analysis_id)
        self.assertEqual((('A', 'retest'), ('B', 'retest')), another.plan)

    def test_database_kind_is_checked(self):
        with closing(initialize_station(sqlite3.connect(':memory:'))) as station:
            with self.assertRaises(ValueError):
                ReviewStore(station).initialize()
            self.assertEqual([], station.execute("SELECT name FROM sqlite_master WHERE name = 'accepted_analyses'").fetchall())
