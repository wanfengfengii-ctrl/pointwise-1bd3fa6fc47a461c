from collections import defaultdict
from dataclasses import dataclass

from costs.normalize import CostBasis


@dataclass(frozen=True, slots=True)
class CutObjective:
    segment_ids: tuple[str, ...]
    source: int
    sink: int
    capacities: tuple[tuple[int, int, int], ...]


def build_cut_objective(basis: CostBasis) -> CutObjective:
    nodes = {segment_id: index for index, segment_id in enumerate(basis.segment_ids)}
    source = len(nodes)
    sink = source + 1
    capacities: dict[tuple[int, int], int] = defaultdict(int)
    for timing in basis.base_timings:
        node = nodes[timing.segment_id]
        edge = (node, sink) if timing.disposition == 'retest' else (source, node)
        capacities[edge] += timing.work
    for timing in basis.changeovers:
        start = nodes[timing.start_segment]
        end = nodes[timing.end_segment]
        if start != end:
            capacities[start, end] += timing.work
    return CutObjective(
        basis.segment_ids,
        source,
        sink,
        tuple((u, v, work) for (u, v), work in sorted(capacities.items()) if work),
    )
