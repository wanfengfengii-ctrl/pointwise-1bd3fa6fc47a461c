import sqlite3
from uuid import uuid4

from execution.intake import validate_actuals
from execution.reconcile import reconcile_plan
from execution.store import ExecutionCloseout, ExecutionStore
from review.reports import read_approved_report


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
