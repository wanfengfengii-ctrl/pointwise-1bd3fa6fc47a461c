from dataclasses import dataclass
import json
import sqlite3

from analysis.artifacts import AnalysisArtifact, decode_artifact, encode_artifact
from review.requests import ReviewRequest


_OFFLINE_ID = 0x5354524E


@dataclass(frozen=True, slots=True)
class DecisionReport:
    report_id: str
    analysis_id: str
    request: ReviewRequest
    status: str
    plan: tuple[tuple[str, str], ...] | None


class ReviewStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        conn = self.connection
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('BEGIN IMMEDIATE')
        with conn:
            application = conn.execute('PRAGMA application_id').fetchone()[0]
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            fresh = (application, version) == (0, 0)
            if fresh:
                existing = conn.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
                if existing is not None:
                    raise ValueError('unrecognized offline database')
            elif (application, version) != (_OFFLINE_ID, 1):
                raise ValueError('incompatible offline database')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS accepted_analyses (
                    analysis_id TEXT PRIMARY KEY NOT NULL,
                    artifact TEXT NOT NULL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS decision_reports (
                    report_id TEXT PRIMARY KEY NOT NULL,
                    analysis_id TEXT NOT NULL REFERENCES accepted_analyses(analysis_id),
                    request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan TEXT,
                    CHECK ((status = 'approved' AND plan IS NOT NULL)
                        OR (status = 'infeasible' AND plan IS NULL))
                )
            ''')
            conn.execute('SELECT analysis_id, artifact FROM accepted_analyses LIMIT 0')
            conn.execute('SELECT report_id, analysis_id, request, status, plan FROM decision_reports LIMIT 0')
            if fresh:
                conn.execute(f'PRAGMA application_id = {_OFFLINE_ID}')
                conn.execute('PRAGMA user_version = 1')

    def load_analysis(self, analysis_id: str) -> AnalysisArtifact:
        row = self.connection.execute(
            'SELECT artifact FROM accepted_analyses WHERE analysis_id = ?', (analysis_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown accepted analysis {analysis_id}')
        return decode_artifact(row[0])

    def insert_analysis(self, analysis: AnalysisArtifact) -> None:
        self.connection.execute(
            'INSERT INTO accepted_analyses (analysis_id, artifact) VALUES (?, ?)',
            (analysis.analysis_id, encode_artifact(analysis)),
        )

    def insert_report(self, report: DecisionReport) -> None:
        request = json.dumps(report.request.assignments, separators=(',', ':'))
        plan = None if report.plan is None else json.dumps(report.plan, separators=(',', ':'))
        self.connection.execute('''
            INSERT INTO decision_reports (report_id, analysis_id, request, status, plan)
            VALUES (?, ?, ?, ?, ?)
        ''', (report.report_id, report.analysis_id, request, report.status, plan))

    def load_report(self, report_id: str) -> DecisionReport:
        row = self.connection.execute(
            'SELECT analysis_id, request, status, plan FROM decision_reports WHERE report_id = ?', (report_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown decision report {report_id}')
        analysis_id, request, status, plan = row
        assignments = tuple(tuple(entry) for entry in json.loads(request))
        return DecisionReport(
            report_id, analysis_id, ReviewRequest(assignments), status,
            None if plan is None else tuple(tuple(entry) for entry in json.loads(plan)),
        )
