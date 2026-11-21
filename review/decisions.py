from collections import defaultdict, deque
import sqlite3
from uuid import uuid4

from analysis.artifacts import AnalysisArtifact
from review.imports import resolve_analysis
from review.requests import ReviewRequest, validate_request
from review.slots import assign_slots, validate_compatibility, validate_open_slots
from review.store import DecisionReport, ReviewStore, WorkOrderReport


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


def issue_work_order(
    connection: sqlite3.Connection,
    requirements,
    open_slots,
    compatibility,
    *,
    analysis_id: str,
) -> WorkOrderReport:
    store = ReviewStore(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        if type(analysis_id) is not str or not analysis_id:
            raise ValueError('invalid analysis id')
        analysis = store.load_analysis(analysis_id)
        request = validate_request(analysis.public_segments, requirements)
        slots = validate_open_slots(open_slots)
        compat = validate_compatibility(analysis.public_segments, slots, compatibility)
        assignment = assign_slots(analysis, request, slots, compat)
        report = WorkOrderReport(
            report_id=f'report-{uuid4().hex}',
            analysis_id=analysis.analysis_id,
            request=request,
            open_slots=slots,
            compatibility=compat,
            status='infeasible' if assignment is None else 'approved',
            assignment=assignment,
        )
        store.insert_work_order(report)
    return report
