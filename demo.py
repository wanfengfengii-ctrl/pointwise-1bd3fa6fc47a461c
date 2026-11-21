from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from analysis.archive import AnalysisArchive
from analysis.publish import publish_analysis
from batches.intake import put_batch
from batches.segments import Segment
from batches.store import BatchStore
from batches.timings import BaseTiming, ChangeoverTiming
from costs.ledger import score_batch
from execution.closeout import close_execution
from execution.intake import ActualDisposition
from execution.store import ExecutionStore
from review.decisions import review_plan
from review.reports import read_result
from review.store import ReviewStore


def _sample(name: str) -> dict:
    path = Path(__file__).resolve().parent / 'samples' / name
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    day = _sample('day_batch.json')
    night = _sample('night_shift.json')
    segments = tuple(Segment(segment_id) for segment_id in day['segments'])
    bases = tuple(BaseTiming(*row) for row in day['base_timings'])
    extras = tuple(ChangeoverTiming(*row) for row in day['changeovers'])
    correction = day['correction']
    corrected = tuple(
        replace(timing, amount=correction['amount']) if timing.timing_id == correction['timing_id'] else timing
        for timing in bases
    )
    batch_id, public, policy = day['batch_id'], day['public_segments'], day['policy_version']
    with TemporaryDirectory() as directory:
        station_path = Path(directory, 'station.db')
        offline_path = Path(directory, 'offline.db')
        with closing(sqlite3.connect(station_path)) as station:
            BatchStore(station).initialize()
            AnalysisArchive(station).initialize()
            original = put_batch(station, batch_id, segments, public, bases, extras)
            revision = put_batch(station, batch_id, segments, public, corrected, extras, parent_revision_id=original)
            assert BatchStore(station).load_revision(revision).parent_revision_id == original
            score = score_batch(station, revision, policy, day['station_plan'])
            analysis = publish_analysis(station, revision, policy)
            assert 'H-internal' not in analysis.artifact and 'edge-ah' not in analysis.artifact

        with closing(sqlite3.connect(offline_path)) as offline:
            ReviewStore(offline).initialize()
            ExecutionStore(offline).initialize()
            conflict = review_plan(offline, night['requests']['conflict'], artifact=analysis.artifact)
            reverse = review_plan(offline, night['requests']['reverse'], analysis_id=analysis.analysis_id)
            work_order = review_plan(offline, night['requests']['work_order'], analysis_id=analysis.analysis_id)
            assert conflict.status == 'infeasible' and conflict.plan is None, 'JOINT_REQUEST_FALSE_APPROVAL'

        with closing(sqlite3.connect(station_path)) as station:
            BatchStore(station).initialize()
            AnalysisArchive(station).initialize()
            later = put_batch(station, batch_id, segments, public, corrected, ())
            publish_analysis(station, later, policy)
            assert AnalysisArchive(station).load_analysis(analysis.analysis_id) == analysis

        with closing(sqlite3.connect(offline_path)) as offline:
            ReviewStore(offline).initialize()
            ExecutionStore(offline).initialize()
            actuals = tuple(ActualDisposition(*row) for row in night['actuals'])
            closeout = close_execution(offline, work_order.report_id, actuals)
        with closing(sqlite3.connect(offline_path)) as offline:
            original_report = read_result(offline, work_order.report_id)
            original_closeout = read_result(offline, closeout.closeout_id, report_id=work_order.report_id)
            assert original_report == work_order and original_closeout == closeout

    expected = {
        'score': 1, 'charged': ['edge-ah'], 'minimum_work': 0,
        'conflict': 'infeasible', 'reverse': [['A', 'release'], ['B', 'retest'], ['C', 'retest']],
        'plan': [['A', 'retest'], ['B', 'retest'], ['C', 'retest']],
    }
    actual = {
        'score': score.total_work,
        'charged': [entry.timing_id for entry in score.entries if entry.kind == 'changeover'],
        'minimum_work': analysis.minimum_work,
        'conflict': conflict.status,
        'reverse': [list(row) for row in reverse.plan or ()],
        'plan': [list(row) for row in original_report.plan or ()],
    }
    downstream_expected = [['B', 'different', 'retest', 'release'], ['C', 'missing', 'retest', None]]
    downstream_actual = [
        [finding.segment_id, finding.kind, finding.planned, finding.actual]
        for finding in original_closeout.findings
    ]
    assert actual == expected, (expected, actual)
    assert downstream_actual == downstream_expected, (downstream_expected, downstream_actual)
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'T7',
        'input': {'day': day, 'night': night},
        'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['costs/ledger.py', 'analysis/publish.py', 'review/decisions.py', 'execution/reconcile.py'],
        'oracle': '手算 A 到 H 加时为 1。零工时要求 C 复测且 A 复测时 B 随之复测。逐段对照实际可知 B 不一致、C 缺报。',
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
