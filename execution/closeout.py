import sqlite3
from uuid import uuid4

from execution.intake import validate_actuals, validate_work_actuals
from execution.reconcile import reconcile_plan, reconcile_work_order
from execution.store import ExecutionCloseout, ExecutionStore, WorkOrderCloseout
from review.reports import read_approved_report, read_approved_work_order


def close_execution(connection: sqlite3.Connection, report_id: str, actuals) -> ExecutionCloseout:
    store = ExecutionStore(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        report = read_approved_report(connection, report_id)
        records = validate_actuals(report.plan, actuals)
        findings = reconcile_plan(report.plan, records)
        closeout = ExecutionCloseout(f'closeout-{uuid4().hex}', report.report_id, records, findings)
        store.insert_closeout(closeout)
    return closeout


def close_work_order(connection: sqlite3.Connection, report_id: str, actuals) -> WorkOrderCloseout:
    store = ExecutionStore(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        order = read_approved_work_order(connection, report_id)
        records = validate_work_actuals(order.assignment, actuals)
        findings = reconcile_work_order(order.assignment, records)
        closeout = WorkOrderCloseout(f'closeout-{uuid4().hex}', order.report_id, records, findings)
        store.insert_work_closeout(closeout)
    return closeout
