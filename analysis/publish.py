import sqlite3
from uuid import uuid4

from analysis.archive import AnalysisArchive, SavedAnalysis
from analysis.artifacts import AnalysisArtifact
from analysis.objective import build_cut_objective
from analysis.projection import project_public_evidence
from analysis.solver import solve_minimum
from batches.store import BatchStore
from costs.normalize import normalize_basis
from costs.policies import get_policy


def publish_analysis(connection: sqlite3.Connection, revision_id: str, policy_version: str) -> SavedAnalysis:
    policy = get_policy(policy_version)
    batches = BatchStore(connection)
    archive = AnalysisArchive(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        revision = batches.load_revision(revision_id)
        basis = normalize_basis(revision, policy)
        objective = build_cut_objective(basis)
        minimum = solve_minimum(objective)
        evidence = project_public_evidence(objective, minimum, revision.public_segments)
        artifact = AnalysisArtifact(
            version=1,
            analysis_id=f'analysis-{uuid4().hex}',
            batch_id=revision.batch_id,
            revision_id=revision.revision_id,
            policy_version=policy.version,
            minimum_work=minimum.minimum_work,
            public_segments=revision.public_segments,
            evidence=evidence,
        )
        if not revision.frozen:
            batches.save_frozen_revision(revision.freeze())
        saved = archive.insert_analysis(artifact)
    return saved
