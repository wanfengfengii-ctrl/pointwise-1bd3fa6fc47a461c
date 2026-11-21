from contextlib import closing
from itertools import product
from random import Random
import sqlite3
import unittest

from analysis.artifacts import decode_artifact
from analysis.objective import build_cut_objective
from analysis.publish import publish_analysis
from analysis.solver import solve_minimum
from batches.intake import put_batch
from batches.segments import Segment
from batches.store import BatchStore
from batches.timings import BaseTiming, ChangeoverTiming
from costs.ledger import score_batch
from costs.normalize import normalize_basis
from costs.policies import get_policy
from review.decisions import review_plan
from tests.test_analysis import admitted_rows
from tests.test_workflow import POLICY, initialize_offline, initialize_station


class OracleTests(unittest.TestCase):
    def test_exhaustive_oracle(self):
        rng = Random(812)
        ids = ('C', 'H-internal', 'A', 'B')
        public = ('C', 'A', 'B')
        segments = tuple(Segment(part) for part in ids)
        cases = [
            (((2, 0), (0, 0), (0, 0), (0, 0)), ((2, 1, 1), (1, 3, 1))),
            (((0, 2), (0, 0), (0, 0), (0, 0)), ((2, 1, 2), (1, 3, 1), (2, 1, 3), (3, 2, 4))),
            (((0, 0),) * 4, ()),
        ]
        for _ in range(12):
            base = tuple((rng.randrange(4), rng.randrange(4)) for _ in ids)
            links = tuple((rng.randrange(4), rng.randrange(4), rng.randrange(4)) for _ in range(8))
            cases.append((base, links))

        with closing(initialize_station(sqlite3.connect(':memory:'))) as station:
            with closing(initialize_offline(sqlite3.connect(':memory:'))) as offline:
                for index, (base, links) in enumerate(cases):
                    with self.subTest(case=index):
                        self.check_case(station, offline, ids, public, segments, base, links, index)

    def check_case(self, station, offline, ids, public, segments, base, links, index):
        dispositions = ('release', 'retest')
        bases = tuple(
            BaseTiming(f'base-{i}-{bit}', part, dispositions[bit], base[i][bit])
            for i, part in enumerate(ids) for bit in (0, 1)
        )
        extras = tuple(
            ChangeoverTiming(f'link-{i}', ids[start], ids[end], charge)
            for i, (start, end, charge) in enumerate(links)
        )
        revision_id = put_batch(station, f'case-{index}', segments, reversed(public), bases, extras)
        scored = {}
        for bits in product((0, 1), repeat=len(ids)):
            value = sum(base[i][bit] for i, bit in enumerate(bits))
            value += sum(charge for start, end, charge in links if bits[start] == 1 and bits[end] == 0)
            scored[bits] = value
            plan = {part: dispositions[bit] for part, bit in zip(ids, bits)}
            self.assertEqual(value, score_batch(station, revision_id, POLICY, plan).total_work)
        best = min(scored.values())
        positions = tuple(ids.index(part) for part in public)
        projected = {
            tuple(bits[position] for position in positions)
            for bits, value in scored.items() if value == best
        }
        saved = publish_analysis(station, revision_id, POLICY)
        artifact = decode_artifact(saved.artifact)
        self.assertEqual((best, public), (artifact.minimum_work, artifact.public_segments))
        self.assertEqual(projected, admitted_rows(artifact))
        self.assertEqual(
            tuple(part for i, part in enumerate(public) if all(row[i] == 1 for row in projected)),
            artifact.evidence.forced_retest,
        )
        self.assertEqual(
            tuple(part for i, part in enumerate(public) if all(row[i] == 0 for row in projected)),
            artifact.evidence.forced_release,
        )
        revision = BatchStore(station).load_revision(revision_id)
        solver_result = solve_minimum(build_cut_objective(normalize_basis(revision, get_policy(POLICY))))
        representative = tuple(dispositions.index(state) for _, state in solver_result.representative)
        self.assertEqual(best, scored[representative])

        for partial in product((None, 0, 1), repeat=len(public)):
            expected = {row for row in projected if all(bit is None or bit == row[i] for i, bit in enumerate(partial))}
            request = {part: dispositions[bit] for part, bit in zip(public, partial) if bit is not None}
            report = review_plan(offline, request, artifact=saved.artifact)
            self.assertEqual('approved' if expected else 'infeasible', report.status)
            if expected:
                self.assertEqual(public, tuple(part for part, _ in report.plan))
                actual = tuple(dispositions.index(state) for _, state in report.plan)
                self.assertIn(actual, expected)
            else:
                self.assertIsNone(report.plan)
