from dataclasses import asdict, dataclass
import json
import sqlite3

from execution.intake import ActualDisposition
from execution.reconcile import SegmentFinding


@dataclass(frozen=True, slots=True)
class ExecutionCloseout:
    closeout_id: str
    report_id: str
    actuals: tuple[ActualDisposition, ...]
    findings: tuple[SegmentFinding, ...]


class ExecutionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        conn = self.connection
        conn.execute('BEGIN IMMEDIATE')
        with conn:
            conn.execute('SELECT report_id FROM decision_reports LIMIT 0')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS execution_closeouts (
                    closeout_id TEXT PRIMARY KEY NOT NULL,
                    report_id TEXT NOT NULL REFERENCES decision_reports(report_id),
                    actuals TEXT NOT NULL,
                    findings TEXT NOT NULL
                )
            ''')
            conn.execute('SELECT closeout_id, report_id, actuals, findings FROM execution_closeouts LIMIT 0')

    def insert_closeout(self, closeout: ExecutionCloseout) -> None:
        self.connection.execute('''
            INSERT INTO execution_closeouts (closeout_id, report_id, actuals, findings)
            VALUES (?, ?, ?, ?)
        ''', (
            closeout.closeout_id,
            closeout.report_id,
            json.dumps([asdict(actual) for actual in closeout.actuals], separators=(',', ':')),
            json.dumps([asdict(finding) for finding in closeout.findings], separators=(',', ':')),
        ))

    def load_closeout(self, closeout_id: str, *, report_id: str | None = None) -> ExecutionCloseout:
        row = self.connection.execute(
            'SELECT report_id, actuals, findings FROM execution_closeouts WHERE closeout_id = ?',
            (closeout_id,),
        ).fetchone()
        if row is None or (report_id is not None and row[0] != report_id):
            raise LookupError(f'no matching execution closeout {closeout_id}')
        return ExecutionCloseout(
            closeout_id,
            row[0],
            tuple(ActualDisposition(**actual) for actual in json.loads(row[1])),
            tuple(SegmentFinding(**finding) for finding in json.loads(row[2])),
        )
