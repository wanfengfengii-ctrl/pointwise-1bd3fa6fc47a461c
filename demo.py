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
from execution.closeout import close_execution, close_work_order
from execution.intake import ActualDisposition
from execution.store import ExecutionStore
from review.decisions import issue_work_order, review_plan
from review.imports import accept_analysis
from review.reports import read_result
from review.store import ReviewStore
from tests.test_workflow import (
    POLICY, initialize_offline, initialize_station, put_bridge, put_reassign, refuse_commit,
)


def _sample(name: str) -> dict:
    path = Path(__file__).resolve().parent / 'samples' / name
    return json.loads(path.read_text(encoding='utf-8'))


def day_shift_scenario() -> None:
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


def work_order_scenario() -> None:
    cases = _sample('slot_shift.json')
    shared, alternate, reassign = cases['shared'], cases['alternate'], cases['reassign']
    with TemporaryDirectory() as directory:
        station_path = Path(directory, 'station.db')
        offline_path = Path(directory, 'offline.db')
        with closing(initialize_station(sqlite3.connect(station_path))) as station:
            bridge = publish_analysis(station, put_bridge(station), POLICY)
            moved = publish_analysis(station, put_reassign(station), POLICY)
        assert (bridge.minimum_work, moved.minimum_work) == (0, 0)

        # 站库已关闭：断源后凭已接纳分析开单、核销。
        with closing(initialize_offline(sqlite3.connect(offline_path))) as offline:
            accepted = accept_analysis(offline, bridge.artifact)
            accepted_moved = accept_analysis(offline, moved.artifact)
            order = issue_work_order(
                offline, {}, shared['open_slots'], shared['compatibility'],
                analysis_id=accepted.analysis_id,
            )
            contested = issue_work_order(
                offline, {'A': 'retest'}, shared['open_slots'], shared['compatibility'],
                analysis_id=accepted.analysis_id,
            )
            choice = issue_work_order(
                offline, {}, alternate['open_slots'], alternate['compatibility'],
                analysis_id=accepted.analysis_id,
            )
            moved_order = issue_work_order(
                offline, {}, reassign['open_slots'], reassign['compatibility'],
                analysis_id=accepted_moved.analysis_id,
            )
            withdrawn = issue_work_order(
                offline, {},
                [slot for slot in reassign['open_slots'] if slot != 'L2'],
                [row for row in reassign['compatibility'] if row[2] != 'L2'],
                analysis_id=accepted_moved.analysis_id,
            )
            closed = close_work_order(offline, order.report_id, shared['actuals'])
            picked = {segment: (disposition, slot) for segment, disposition, slot in choice.assignment}
            other = 'L2' if picked['A'][1] == 'L1' else 'L1'
            deviated = close_work_order(offline, choice.report_id, [('A', 'release', other)])
            with refuse_commit(offline):
                try:
                    issue_work_order(
                        offline, {}, shared['open_slots'], shared['compatibility'],
                        analysis_id=accepted.analysis_id,
                    )
                except sqlite3.DatabaseError:
                    pass
                else:
                    raise AssertionError('expected the work order commit to be refused')
            assert not offline.in_transaction
            retried = issue_work_order(
                offline, {}, shared['open_slots'], shared['compatibility'],
                analysis_id=accepted.analysis_id,
            )
            assert retried.assignment == order.assignment

        # 重开离线库领取已存开单与核销。
        with closing(initialize_offline(sqlite3.connect(offline_path))) as offline:
            assert read_result(offline, order.report_id) == order
            assert read_result(offline, contested.report_id) == contested
            assert read_result(offline, moved_order.report_id) == moved_order
            assert read_result(offline, closed.closeout_id, report_id=order.report_id) == closed
            assert read_result(offline, deviated.closeout_id, report_id=choice.report_id) == deviated

    expected = {
        'shared_assignment': [['A', 'release', 'L1'], ['B', 'retest', 'R1']],
        'shared_contested': 'infeasible',
        'shared_findings': [['A', 'slot'], ['B', 'missing']],
        'alternate_b': ['retest', 'R1'],
        'alternate_findings': [['A', 'slot'], ['B', 'missing']],
        'reassign_assignment': [['C', 'release', 'L2'], ['A', 'release', 'L1'], ['B', 'retest', 'R1']],
        'reassign_withdrawn': 'infeasible',
    }
    actual = {
        'shared_assignment': [list(row) for row in order.assignment or ()],
        'shared_contested': contested.status,
        'shared_findings': [list(row) for row in closed.findings],
        'alternate_b': list(picked['B']),
        'alternate_findings': [list(row) for row in deviated.findings],
        'reassign_assignment': [list(row) for row in moved_order.assignment or ()],
        'reassign_withdrawn': withdrawn.status,
    }
    assert picked['A'][0] == 'release' and picked['A'][1] in ('L1', 'L2')
    assert actual == expected, (expected, actual)
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'T8',
        'input': cases,
        'expected': expected, 'actual': actual,
        'code_paths': ['review/decisions.py', 'review/slots.py', 'execution/closeout.py', 'execution/reconcile.py'],
        'oracle': '手算 断源开单：shared 空申请唯解 A 放行 L1、B 复测 R1；A 复测蕴含 B 复测，两段争用 R1 不可行。'
                  'reassign 最低工时 0 强制 C 放行，唯解 C 放行 L2、A 放行 L1、B 复测 R1；撤下 L2 后不可行。'
                  '核销只按原指派判差：A 实报另一兼容槽仍记错槽，B 未报记缺报。',
    }, ensure_ascii=False, sort_keys=True))


def main() -> None:
    day_shift_scenario()
    work_order_scenario()


if __name__ == '__main__':
    main()
