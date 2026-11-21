import sqlite3

from analysis.artifacts import AnalysisArtifact, decode_artifact
from review.store import ReviewStore


def resolve_analysis(
    store: ReviewStore, *, analysis_id: str | None = None, artifact: str | None = None,
) -> AnalysisArtifact:
    if (analysis_id is None) == (artifact is None):
        raise ValueError('supply exactly one analysis source')
    if artifact is None:
        if type(analysis_id) is not str or not analysis_id:
            raise ValueError('invalid analysis id')
        return store.load_analysis(analysis_id)

    candidate = decode_artifact(artifact)
    try:
        saved = store.load_analysis(candidate.analysis_id)
    except LookupError:
        store.insert_analysis(candidate)
        return candidate
    if saved != candidate:
        raise ValueError('analysis id already identifies a different artifact')
    return saved


def accept_analysis(connection: sqlite3.Connection, artifact: str) -> AnalysisArtifact:
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        accepted = resolve_analysis(ReviewStore(connection), artifact=artifact)
    return accepted
