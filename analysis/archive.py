from dataclasses import dataclass
import sqlite3

from analysis.artifacts import AnalysisArtifact, decode_artifact, encode_artifact


@dataclass(frozen=True, slots=True)
class SavedAnalysis:
    analysis_id: str
    batch_id: str
    revision_id: str
    policy_version: str
    minimum_work: int
    artifact: str


def _saved(analysis: AnalysisArtifact, encoded: str) -> SavedAnalysis:
    return SavedAnalysis(
        analysis.analysis_id, analysis.batch_id, analysis.revision_id,
        analysis.policy_version, analysis.minimum_work, encoded,
    )


class AnalysisArchive:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        conn = self.connection
        conn.execute('BEGIN IMMEDIATE')
        with conn:
            conn.execute('SELECT revision_id FROM batch_revisions LIMIT 0')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS analysis_archive (
                    analysis_id TEXT PRIMARY KEY NOT NULL,
                    revision_id TEXT NOT NULL REFERENCES batch_revisions(revision_id),
                    artifact TEXT NOT NULL
                )
            ''')
            conn.execute('SELECT analysis_id, revision_id, artifact FROM analysis_archive LIMIT 0')

    def insert_analysis(self, analysis: AnalysisArtifact) -> SavedAnalysis:
        encoded = encode_artifact(analysis)
        self.connection.execute(
            'INSERT INTO analysis_archive (analysis_id, revision_id, artifact) VALUES (?, ?, ?)',
            (analysis.analysis_id, analysis.revision_id, encoded),
        )
        return _saved(analysis, encoded)

    def load_analysis(self, analysis_id: str) -> SavedAnalysis:
        row = self.connection.execute(
            'SELECT artifact FROM analysis_archive WHERE analysis_id = ?', (analysis_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown archived analysis {analysis_id}')
        return _saved(decode_artifact(row[0]), row[0])
