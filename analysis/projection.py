from collections import deque

from analysis.artifacts import PublicEvidence
from analysis.objective import CutObjective
from analysis.solver import MinimumResult


def _reachable(residual: tuple[tuple[int, ...], ...], start: int) -> set[int]:
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for target in residual[node]:
            if target not in visited:
                visited.add(target)
                queue.append(target)
    return visited


def project_public_evidence(
    objective: CutObjective, minimum: MinimumResult, public_segments: tuple[str, ...],
) -> PublicEvidence:
    nodes = {segment_id: index for index, segment_id in enumerate(objective.segment_ids)}
    public_nodes = [(segment_id, nodes[segment_id]) for segment_id in public_segments]
    from_source = _reachable(minimum.residual, objective.source)
    forced_retest = tuple(segment_id for segment_id, node in public_nodes if node in from_source)
    forced_release = []
    implications = []
    for segment_id, node in public_nodes:
        reachable = _reachable(minimum.residual, node)
        if objective.sink in reachable:
            forced_release.append(segment_id)
        # Hidden nodes remain reachable until only the public endpoints are selected.
        implications.extend(
            (segment_id, target_id)
            for target_id, target in public_nodes
            if target != node and target in reachable
        )
    return PublicEvidence(forced_retest, tuple(forced_release), tuple(implications))
