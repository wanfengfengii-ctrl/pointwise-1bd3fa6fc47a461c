import sqlite3

from execution.store import ExecutionCloseout, ExecutionStore, WorkOrderCloseout
from review.store import DecisionReport, ReviewStore, WorkOrderReport


def read_result(
    connection: sqlite3.Connection, result_id: str, *, report_id: str | None = None,
) -> DecisionReport | WorkOrderReport | ExecutionCloseout | WorkOrderCloseout:
    if type(result_id) is not str or not result_id:
        raise ValueError('invalid result id')
    if result_id.startswith('closeout-'):
        store = ExecutionStore(connection)
        try:
            return store.load_closeout(result_id, report_id=report_id)
        except LookupError:
            return store.load_work_closeout(result_id, report_id=report_id)
    if report_id is not None:
        raise ValueError('a parent report id can only qualify a closeout')
    store = ReviewStore(connection)
    try:
        return store.load_report(result_id)
    except LookupError:
        return store.load_work_order(result_id)


def read_approved_report(connection: sqlite3.Connection, report_id: str) -> DecisionReport:
    store = ReviewStore(connection)
    try:
        report = store.load_report(report_id)
    except LookupError:
        store.load_work_order(report_id)
        raise ValueError('report does not authorize execution')
    if report.status != 'approved' or report.plan is None:
        raise ValueError('report does not authorize execution')
    return report


def read_approved_work_order(connection: sqlite3.Connection, report_id: str) -> WorkOrderReport:
    store = ReviewStore(connection)
    try:
        order = store.load_work_order(report_id)
    except LookupError:
        store.load_report(report_id)
        raise ValueError('work order does not authorize closeout')
    if order.status != 'approved' or order.assignment is None:
        raise ValueError('work order does not authorize closeout')
    return order
