"""工場レイアウトの厳密最適化。分枝限定で最適性を証明し、必要なら CP-SAT で incumbent を探す。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.optimizer import (
    Department,
    LayoutProblem,
    OptimizerError,
    Placement,
    Score,
    _candidate_positions,
    _dept_map,
    centroid,
    evaluate,
    manhattan,
    min_cell_distance,
    occupancy,
    share_edge,
)


@dataclass(frozen=True)
class ExactSolveResult:
    placements: list[Placement]
    score: Score
    proven: bool
    objective_bound: float | None
    status: str
    branches: int


def _place_order(problem: LayoutProblem) -> list[Department]:
    flow_sum = {d.id: 0.0 for d in problem.departments}
    for fl in problem.flows:
        if fl.from_id in flow_sum:
            flow_sum[fl.from_id] += fl.volume
        if fl.to_id in flow_sum:
            flow_sum[fl.to_id] += fl.volume
    return sorted(
        problem.departments,
        key=lambda d: (
            0 if d.fixed_row is not None else 1,
            -(d.width * d.height),
            -flow_sum[d.id],
            d.id,
        ),
    )


def _pair_min_table(problem: LayoutProblem) -> dict[tuple[str, str], float]:
    depts = _dept_map(problem)
    table: dict[tuple[str, str], float] = {}
    ids = [d.id for d in problem.departments]
    for a_id in ids:
        for b_id in ids:
            if a_id == b_id:
                continue
            best: float | None = None
            for pa in _candidate_positions(problem, depts[a_id], set()):
                taken = occupancy(pa)
                for pb in _candidate_positions(problem, depts[b_id], taken):
                    dist = manhattan(centroid(pa), centroid(pb))
                    if best is None or dist < best:
                        best = dist
                        if best == 0.0:
                            break
                if best == 0.0:
                    break
            table[(a_id, b_id)] = 0.0 if best is None else best
    return table


def _forbid_ok(problem: LayoutProblem, placed: list[Placement], cand: Placement) -> bool:
    by_id = {p.dept_id: p for p in placed}
    for rel in problem.relations:
        if rel.kind != "forbid":
            continue
        other_id = rel.b if rel.a == cand.dept_id else rel.a if rel.b == cand.dept_id else None
        if other_id is None:
            continue
        other = by_id.get(other_id)
        if other and min_cell_distance(cand, other) < rel.min_cell_distance:
            return False
    return True


def _fits(cand: Placement, taken: set[tuple[int, int]]) -> bool:
    return occupancy(cand).isdisjoint(taken)


def _partial_lower_bound(
    problem: LayoutProblem,
    placed: list[Placement],
    remaining: set[str],
    taken: set[tuple[int, int]],
    pair_min: dict[tuple[str, str], float],
    all_cands: dict[str, list[Placement]],
) -> float:
    by_id = {p.dept_id: p for p in placed}
    cost = 0.0
    for fl in problem.flows:
        pa, pb = by_id.get(fl.from_id), by_id.get(fl.to_id)
        if pa and pb:
            cost += fl.volume * manhattan(centroid(pa), centroid(pb))
        elif pa and fl.to_id in remaining:
            best: float | None = None
            for cand in all_cands[fl.to_id]:
                if not _fits(cand, taken):
                    continue
                dist = manhattan(centroid(pa), centroid(cand))
                if best is None or dist < best:
                    best = dist
            cost += fl.volume * (best if best is not None else pair_min[(fl.from_id, fl.to_id)])
        elif pb and fl.from_id in remaining:
            best = None
            for cand in all_cands[fl.from_id]:
                if not _fits(cand, taken):
                    continue
                dist = manhattan(centroid(cand), centroid(pb))
                if best is None or dist < best:
                    best = dist
            cost += fl.volume * (best if best is not None else pair_min[(fl.from_id, fl.to_id)])
        elif fl.from_id in remaining and fl.to_id in remaining:
            cost += fl.volume * pair_min[(fl.from_id, fl.to_id)]

    for rel in problem.relations:
        if rel.kind != "prefer":
            continue
        pa, pb = by_id.get(rel.a), by_id.get(rel.b)
        if pa and pb and not share_edge(pa, pb):
            cost += problem.adjacency_weight

    chain = problem.process_chain
    if len(chain) >= 2:
        for prev_id, next_id in zip(chain, chain[1:], strict=False):
            pa, pb = by_id.get(prev_id), by_id.get(next_id)
            if not pa or not pb:
                continue
            ra, rb = centroid(pa)[0], centroid(pb)[0]
            if rb + 0.25 < ra:
                cost += problem.process_weight * (ra - rb)
    return cost


def solve_exact_bnb(
    problem: LayoutProblem,
    *,
    time_limit_ms: int | None = 45_000,
    hint: list[Placement] | None = None,
) -> ExactSolveResult:
    order = _place_order(problem)
    pair_min = _pair_min_table(problem)
    all_cands = {d.id: _candidate_positions(problem, d, set()) for d in problem.departments}
    deadline = time.perf_counter() + (time_limit_ms or 45_000) / 1000.0
    nodes = 0
    timed_out = False

    best: list[Placement] | None = None
    best_score: Score | None = None
    if hint:
        scored = evaluate(problem, hint)
        if scored.feasible:
            best, best_score = list(hint), scored

    def rec(index: int, placed: list[Placement], taken: set[tuple[int, int]]) -> None:
        nonlocal best, best_score, nodes, timed_out
        if time.perf_counter() >= deadline:
            timed_out = True
            return
        nodes += 1
        remaining = {d.id for d in order[index:]}
        bound = _partial_lower_bound(problem, placed, remaining, taken, pair_min, all_cands)
        if best_score is not None and bound + 1e-12 >= best_score.total:
            return
        if index == len(order):
            score = evaluate(problem, placed)
            if score.feasible and (best_score is None or score.total + 1e-12 < best_score.total):
                best, best_score = list(placed), score
            return
        dept = order[index]
        scored_cands: list[tuple[float, Placement]] = []
        for cand in all_cands[dept.id]:
            if not _fits(cand, taken) or not _forbid_ok(problem, placed, cand):
                continue
            nxt_taken = taken | occupancy(cand)
            lb = _partial_lower_bound(
                problem, [*placed, cand], {d.id for d in order[index + 1 :]}, nxt_taken, pair_min, all_cands
            )
            scored_cands.append((lb, cand))
        scored_cands.sort(key=lambda item: item[0])
        for lb, cand in scored_cands:
            if timed_out:
                return
            if best_score is not None and lb + 1e-12 >= best_score.total:
                continue
            rec(index + 1, [*placed, cand], taken | occupancy(cand))

    rec(0, [], set())
    if best is None or best_score is None:
        raise OptimizerError("厳密ソルバが実行可能解を見つけられませんでした")
    proven = not timed_out
    return ExactSolveResult(
        placements=best,
        score=best_score,
        proven=proven,
        objective_bound=best_score.total if proven else None,
        status="OPTIMAL" if proven else "FEASIBLE",
        branches=nodes,
    )


def solve_exact(
    problem: LayoutProblem,
    *,
    time_limit_ms: int | None = 25_000,
    hint: list[Placement] | None = None,
) -> ExactSolveResult:
    """同じ目的関数を分枝限定で最小化し、制限時間内に探索し切れたときだけ最適と証明する。"""
    return solve_exact_bnb(problem, time_limit_ms=time_limit_ms or 45_000, hint=hint)
