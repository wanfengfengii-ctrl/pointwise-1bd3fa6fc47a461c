from collections import deque
from dataclasses import dataclass

from analysis.objective import CutObjective


@dataclass(frozen=True, slots=True)
class MinimumResult:
    minimum_work: int
    representative: tuple[tuple[str, str], ...]
    residual: tuple[tuple[int, ...], ...]


def _search(network: list[dict[int, int]], source: int, sink: int) -> dict[int, int]:
    parents = {source: source}
    queue = deque([source])
    while queue and sink not in parents:
        node = queue.popleft()
        for target, capacity in network[node].items():
            if capacity > 0 and target not in parents:
                parents[target] = node
                queue.append(target)
    return parents


def solve_minimum(objective: CutObjective) -> MinimumResult:
    source, sink = objective.source, objective.sink
    network: list[dict[int, int]] = [{} for _ in range(sink + 1)]
    for start, end, capacity in objective.capacities:
        network[start][end] = capacity
        network[end].setdefault(start, 0)

    flow = 0
    while True:
        parents = _search(network, source, sink)
        if sink not in parents:
            break
        path = []
        node = sink
        while node != source:
            previous = parents[node]
            path.append((previous, node))
            node = previous
        increment = min(network[start][end] for start, end in path)
        for start, end in path:
            network[start][end] -= increment
            network[end][start] += increment
        flow += increment

    representative = tuple(
        (segment_id, 'retest' if node in parents else 'release')
        for node, segment_id in enumerate(objective.segment_ids)
    )
    residual = tuple(tuple(sorted(target for target, work in edges.items() if work > 0)) for edges in network)
    return MinimumResult(flow, representative, residual)
