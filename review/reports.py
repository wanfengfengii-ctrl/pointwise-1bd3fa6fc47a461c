import sqlite3

from execution.store import ExecutionCloseout, ExecutionStore
from review.store import DecisionReport, ReviewStore


def read_result(
    connection: sqlite3.Connection, result_id: str, *, report_id: str | None = None,
) -> DecisionReport | ExecutionCloseout:
    if type(result_id) is not str or not result_id:
        raise ValueError('invalid result id')
    if result_id.startswith('closeout-'):
        return ExecutionStore(connection).load_closeout(result_id, report_id=report_id)
    if report_id is not None:
        raise ValueError('a parent report id can only qualify a closeout')
    return ReviewStore(connection).load_report(result_id)


def read_approved_report(connection: sqlite3.Connection, report_id: str) -> DecisionReport:
    report = ReviewStore(connection).load_report(report_id)
    if report.status != 'approved' or report.plan is None:
        raise ValueError('report does not authorize execution')
    return report
