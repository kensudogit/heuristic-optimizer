"""小規模インスタンスで工場レイアウト探索の妥当性を見る。"""

from __future__ import annotations

import itertools

import pytest

from app.services.optimizer import (
    Department,
    Flow,
    LayoutProblem,
    OptimizerError,
    Placement,
    Relation,
    evaluate,
    exact_best_if_tractable,
    explain_proposal,
    flow_lower_bound,
    greedy_layout,
    optimize,
    process_path,
    sample_factory,
)


def _tiny() -> LayoutProblem:
    return LayoutProblem(
        rows=2,
        cols=2,
        departments=[
            Department("A", "受入", 1, 1, rotatable=False),
            Department("B", "加工", 1, 1, rotatable=False),
            Department("C", "出荷", 1, 1, rotatable=False),
        ],
        flows=[Flow("A", "B", 10), Flow("B", "C", 1)],
    )


def _brute_best(problem: LayoutProblem) -> float:
    cells = [(r, c) for r in range(problem.rows) for c in range(problem.cols)]
    best = 1e18
    for chosen in itertools.permutations(cells, len(problem.departments)):
        placements = [
            Placement(d.id, r, c, d.width, d.height)
            for d, (r, c) in zip(problem.departments, chosen, strict=True)
        ]
        score = evaluate(problem, placements)
        if score.feasible:
            best = min(best, score.total)
    return best


def test_exact_solver_matches_enumeration_and_proves() -> None:
    problem = _tiny()
    result = optimize(problem, seed=1, exact=True, time_limit_ms=5_000, n_proposals=1)
    exact = _brute_best(problem)
    assert result.optimal is True
    assert result.best_score.total == pytest.approx(exact)
    assert result.exact_best == pytest.approx(exact)
    assert result.optimality_gap == pytest.approx(0.0)
    assert result.proposals[0].label == "最適解"


def test_tiny_instance_matches_enumeration() -> None:
    problem = _tiny()
    result = optimize(problem, seed=1, max_passes=30)
    exact = _brute_best(problem)
    assert result.best_score.feasible
    assert result.best_score.total == pytest.approx(exact)
    assert result.best_score.total <= result.initial_score.total + 1e-12
    assert result.exact_best == pytest.approx(exact)
    assert result.optimality_gap == pytest.approx(0.0)
    assert flow_lower_bound(problem) <= exact + 1e-12


def test_high_flow_pair_is_adjacent_on_tiny_grid() -> None:
    result = optimize(_tiny(), max_passes=20)
    by_id = {p.dept_id: p for p in result.best_placements}
    dist = abs(by_id["A"].row - by_id["B"].row) + abs(by_id["A"].col - by_id["B"].col)
    assert dist == 1


def test_sample_factory_is_feasible() -> None:
    result = optimize(sample_factory(), seed=1, max_passes=40)
    assert result.initial_score.feasible
    assert result.best_score.feasible
    assert result.best_score.total <= result.initial_score.total + 1e-12
    assert len(result.best_placements) == 7
    ship = next(p for p in result.best_placements if p.dept_id == "ship")
    assert (ship.row, ship.col) == (8, 0)


def test_forbid_distance_is_kept() -> None:
    result = optimize(sample_factory(), seed=2, max_passes=40)
    by_id = {p.dept_id: p for p in result.best_placements}
    from app.services.optimizer import min_cell_distance

    assert min_cell_distance(by_id["haz"], by_id["office"]) >= 3


def test_seed_is_reproducible() -> None:
    problem = sample_factory()
    a = optimize(problem, seed=7, max_passes=25)
    b = optimize(problem, seed=7, max_passes=25)
    pos_a = {(p.dept_id, p.row, p.col, p.width, p.height) for p in a.best_placements}
    pos_b = {(p.dept_id, p.row, p.col, p.width, p.height) for p in b.best_placements}
    assert pos_a == pos_b
    assert a.best_score.total == pytest.approx(b.best_score.total)


def test_empty_departments_rejected() -> None:
    with pytest.raises(OptimizerError, match="空"):
        optimize(LayoutProblem(rows=4, cols=4, departments=[], flows=[]))


def test_oversized_department_rejected() -> None:
    with pytest.raises(OptimizerError, match="敷地より大きい"):
        optimize(
            LayoutProblem(
                rows=2,
                cols=2,
                departments=[Department("A", "巨大棟", 5, 5)],
                flows=[],
            )
        )


def test_sample_returns_multiple_proposals() -> None:
    result = optimize(sample_factory(), seed=1, max_passes=25, n_proposals=3)
    assert len(result.proposals) >= 1
    assert result.proposals[0].rank == 1
    assert result.best_score.total == pytest.approx(result.proposals[0].score.total)
    assert "受入" in result.proposals[0].process_summary
    assert result.proposals[0].reasons
    assert len(result.proposals[0].path) == 5
    assert result.exact_best is None
    assert result.optimality_gap is None
    assert result.effectiveness is not None
    assert result.effectiveness.lower_bound <= result.best_score.flow_cost + 1e-12
    assert result.effectiveness.proposal_count == len(result.proposals)
    assert 0 < result.effectiveness.utilization <= 1


def test_exact_best_skips_large_buildings() -> None:
    assert exact_best_if_tractable(sample_factory()) is None
    assert exact_best_if_tractable(_tiny()) == pytest.approx(_brute_best(_tiny()))


def test_chain_guide_makes_initial_or_best_aligned() -> None:
    problem = sample_factory()
    initial = greedy_layout(problem)
    result = optimize(problem, seed=1, max_passes=25, n_proposals=3)
    assert result.effectiveness is not None
    assert result.effectiveness.aligned_proposals >= 1
    assert result.best_score.process_aligned or evaluate(problem, initial).process_aligned


def test_sample_exact_is_proven_optimal() -> None:
    result = optimize(sample_factory(), seed=1, exact=True, time_limit_ms=45_000, n_proposals=1)
    assert result.optimal is True
    assert result.best_score.feasible
    assert result.best_score.process_aligned
    assert result.best_score.total == pytest.approx(878.0)
    assert result.optimality_gap == pytest.approx(0.0)
    assert result.proposals[0].label == "最適解"


def test_explain_and_path_use_process_names() -> None:
    problem = sample_factory()
    result = optimize(problem, seed=1, max_passes=20, n_proposals=1)
    reasons = explain_proposal(problem, result.initial_placements, result.best_placements)
    assert any("搬送距離" in text or "流れ" in text or "整列" in text or "逆行" in text for text in reasons)
    path = process_path(problem, result.best_placements)
    assert len(path) == 5
    assert all(len(point) == 2 for point in path)


def test_process_reverse_is_penalized() -> None:
    problem = sample_factory()
    forward = [
        Placement("recv", 0, 0, 3, 2),
        Placement("mach", 2, 0, 4, 3),
        Placement("assy", 5, 0, 4, 3),
        Placement("insp", 8, 4, 2, 2),
        Placement("ship", 8, 0, 3, 2),
        Placement("office", 0, 6, 2, 2),
        Placement("haz", 0, 10, 2, 2),
    ]
    reversed_flow = [
        Placement("recv", 6, 0, 3, 2),
        Placement("mach", 3, 0, 4, 3),
        Placement("assy", 0, 0, 4, 3),
        Placement("insp", 8, 4, 2, 2),
        Placement("ship", 8, 0, 3, 2),
        Placement("office", 0, 6, 2, 2),
        Placement("haz", 0, 10, 2, 2),
    ]
    good = evaluate(problem, forward)
    bad = evaluate(problem, reversed_flow)
    assert good.process_penalty == pytest.approx(0.0)
    assert bad.process_penalty > 0
    assert bad.total > good.total


def test_unplaceable_returns_no_feasible() -> None:
    problem = LayoutProblem(
        rows=2,
        cols=2,
        departments=[
            Department("A", "A", 2, 2),
            Department("B", "B", 2, 2),
        ],
        flows=[],
    )
    with pytest.raises(OptimizerError, match="実行可能解なし"):
        greedy_layout(problem)
