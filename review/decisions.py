from collections import defaultdict, deque
import sqlite3
from uuid import uuid4

from analysis.artifacts import AnalysisArtifact
from review.imports import resolve_analysis
from review.requests import ReviewRequest, validate_request
from review.store import DecisionReport, ReviewStore


def complete_plan(analysis: AnalysisArtifact, request: ReviewRequest) -> tuple[tuple[str, str], ...] | None:
    evidence = analysis.evidence
    must_retest = set(evidence.forced_retest)
    must_release = set(evidence.forced_release)
    for segment_id, disposition in request.assignments:
        selected = must_retest if disposition == 'retest' else must_release
        selected.add(segment_id)

    successors = defaultdict(list)
    for start, end in evidence.implications:
        successors[start].append(end)
    queue = deque(must_retest)
    while queue:
        segment_id = queue.popleft()
        for implied in successors[segment_id]:
            if implied not in must_retest:
                must_retest.add(implied)
                queue.append(implied)
    if must_retest.intersection(must_release):
        return None
    return tuple(
        (segment_id, 'retest' if segment_id in must_retest else 'release')
        for segment_id in analysis.public_segments
    )


def review_plan(
    connection: sqlite3.Connection,
    requirements,
    *,
    analysis_id: str | None = None,
    artifact: str | None = None,
) -> DecisionReport:
    store = ReviewStore(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        analysis = resolve_analysis(store, analysis_id=analysis_id, artifact=artifact)
        request = validate_request(analysis.public_segments, requirements)
        plan = complete_plan(analysis, request)
        report = DecisionReport(
            report_id=f'report-{uuid4().hex}',
            analysis_id=analysis.analysis_id,
            request=request,
            status='infeasible' if plan is None else 'approved',
            plan=plan,
        )
        store.insert_report(report)
    return report
