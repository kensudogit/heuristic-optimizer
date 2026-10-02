"""工場建設レイアウト（施設配置）のヒューリスティック探索。

問題: 敷地グリッド上に建屋・工程を重ねずに配置する。
目的: 物流量 × 重心間マンハッタン距離 + 隣接希望の未達ペナルティ を最小化。
      厳密な最適解は保証しない。
初期解: 物流量の大きい工程から順に、増分費用最小の位置へ置く貪欲法。
改善: 1棟の再配置・回転の局所探索。seed があるときは Simulated Annealing。
実行可能解: 全工程が敷地内・非重複・禁止セル非占有・離隔制約を満たす配置。
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

HARD_INFEASIBLE = 1e12


ROLES = ("inbound", "process", "outbound", "support")


@dataclass(frozen=True)
class Department:
    id: str
    name: str
    width: int
    height: int
    fixed_row: int | None = None
    fixed_col: int | None = None
    rotatable: bool = True
    role: str = "process"


@dataclass(frozen=True)
class Flow:
    from_id: str
    to_id: str
    volume: float


@dataclass(frozen=True)
class Relation:
    a: str
    b: str
    kind: str  # prefer | forbid
    min_cell_distance: int = 0


@dataclass(frozen=True)
class Placement:
    dept_id: str
    row: int
    col: int
    width: int
    height: int


@dataclass
class LayoutProblem:
    rows: int
    cols: int
    departments: list[Department]
    flows: list[Flow]
    relations: list[Relation] = field(default_factory=list)
    blocked: list[tuple[int, int]] = field(default_factory=list)
    adjacency_weight: float = 8.0
    process_chain: list[str] = field(default_factory=list)
    process_weight: float = 12.0


@dataclass(frozen=True)
class Score:
    total: float
    flow_cost: float
    adjacency_penalty: float
    process_penalty: float
    process_aligned: bool
    feasible: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class SearchResult:
    initial_placements: list[Placement]
    best_placements: list[Placement]
    initial_score: Score
    best_score: Score
    improvement: float
    improvement_rate: float
    evaluations: int
    accepted_moves: int
    passes: int
    seed: int | None
    algorithm: str
    note: str
    proposals: list["LayoutProposal"] = field(default_factory=list)
    exact_best: float | None = None
    optimality_gap: float | None = None


@dataclass(frozen=True)
class LayoutProposal:
    rank: int
    label: str
    placements: list[Placement]
    score: Score
    seed_used: int
    process_summary: str
    reasons: tuple[str, ...]
    path: tuple[tuple[float, float], ...]


class OptimizerError(ValueError):
    """入力が探索できないときの業務エラー。"""


def _dept_map(problem: LayoutProblem) -> dict[str, Department]:
    return {d.id: d for d in problem.departments}


def occupancy(p: Placement) -> set[tuple[int, int]]:
    return {
        (r, c)
        for r in range(p.row, p.row + p.height)
        for c in range(p.col, p.col + p.width)
    }


def centroid(p: Placement) -> tuple[float, float]:
    return (p.row + (p.height - 1) / 2.0, p.col + (p.width - 1) / 2.0)


def manhattan(a: tuple[float, float], b: tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _placements_by_id(placements: list[Placement]) -> dict[str, Placement]:
    return {p.dept_id: p for p in placements}


def share_edge(a: Placement, b: Placement) -> bool:
    cells_a, cells_b = occupancy(a), occupancy(b)
    for r, c in cells_a:
        if (r + 1, c) in cells_b or (r - 1, c) in cells_b or (r, c + 1) in cells_b or (r, c - 1) in cells_b:
            return True
    return False


def min_cell_distance(a: Placement, b: Placement) -> int:
    best = 10**9
    for ra, ca in occupancy(a):
        for rb, cb in occupancy(b):
            best = min(best, abs(ra - rb) + abs(ca - cb))
    return best


def evaluate(problem: LayoutProblem, placements: list[Placement]) -> Score:
    """目的関数とハード制約。実行不能なら total を巨大値にする。"""
    violations: list[str] = []
    by_id = _placements_by_id(placements)
    blocked = set(problem.blocked)
    used: dict[tuple[int, int], str] = {}

    if len(placements) != len(problem.departments):
        violations.append("未配置の工程がある")

    for p in placements:
        if p.row < 0 or p.col < 0 or p.row + p.height > problem.rows or p.col + p.width > problem.cols:
            violations.append(f"{p.dept_id} が敷地外")
            continue
        for cell in occupancy(p):
            if cell in blocked:
                violations.append(f"{p.dept_id} が禁止セル {cell} を占有")
            owner = used.get(cell)
            if owner:
                violations.append(f"{p.dept_id} と {owner} が重複")
            used[cell] = p.dept_id

    for rel in problem.relations:
        if rel.kind != "forbid":
            continue
        pa, pb = by_id.get(rel.a), by_id.get(rel.b)
        if pa and pb and min_cell_distance(pa, pb) < rel.min_cell_distance:
            violations.append(f"{rel.a} と {rel.b} の離隔が不足")

    flow_cost = 0.0
    for fl in problem.flows:
        pa, pb = by_id.get(fl.from_id), by_id.get(fl.to_id)
        if not pa or not pb:
            continue
        flow_cost += fl.volume * manhattan(centroid(pa), centroid(pb))

    adjacency_penalty = 0.0
    for rel in problem.relations:
        if rel.kind != "prefer":
            continue
        pa, pb = by_id.get(rel.a), by_id.get(rel.b)
        if pa and pb and not share_edge(pa, pb):
            adjacency_penalty += problem.adjacency_weight

    process_pen, process_aligned = _process_flow_score(problem, by_id)
    feasible = not violations
    total = HARD_INFEASIBLE if not feasible else flow_cost + adjacency_penalty + process_pen
    return Score(
        total=total,
        flow_cost=flow_cost,
        adjacency_penalty=adjacency_penalty,
        process_penalty=process_pen,
        process_aligned=process_aligned,
        feasible=feasible,
        violations=tuple(dict.fromkeys(violations)),
    )


def _process_flow_score(
    problem: LayoutProblem, by_id: dict[str, Placement]
) -> tuple[float, bool]:
    """入庫→製造→出庫が一方向（北から南）に進むかを評価する。逆行にペナルティ。"""
    chain = problem.process_chain
    if len(chain) < 2:
        return 0.0, True
    penalty = 0.0
    aligned = True
    for prev_id, next_id in zip(chain, chain[1:], strict=False):
        pa, pb = by_id.get(prev_id), by_id.get(next_id)
        if not pa or not pb:
            continue
        ra, rb = centroid(pa)[0], centroid(pb)[0]
        if rb + 0.25 < ra:
            aligned = False
            penalty += problem.process_weight * (ra - rb)
    return penalty, aligned


def process_path(problem: LayoutProblem, placements: list[Placement]) -> list[tuple[float, float]]:
    by_id = _placements_by_id(placements)
    return [centroid(by_id[step]) for step in problem.process_chain if step in by_id]


def explain_proposal(
    problem: LayoutProblem,
    initial: list[Placement],
    proposed: list[Placement],
) -> list[str]:
    """初期解と比べて、どの物流が短くなったかを原文の工程名で書く。"""
    names = {d.id: d.name for d in problem.departments}
    init_by = _placements_by_id(initial)
    prop_by = _placements_by_id(proposed)
    reasons: list[str] = []

    deltas: list[tuple[float, str, float, float]] = []
    for fl in problem.flows:
        a0, b0 = init_by.get(fl.from_id), init_by.get(fl.to_id)
        a1, b1 = prop_by.get(fl.from_id), prop_by.get(fl.to_id)
        if not a0 or not b0 or not a1 or not b1:
            continue
        d0 = fl.volume * manhattan(centroid(a0), centroid(b0))
        d1 = fl.volume * manhattan(centroid(a1), centroid(b1))
        label = f"{names.get(fl.from_id, fl.from_id)}→{names.get(fl.to_id, fl.to_id)}"
        deltas.append((d0 - d1, label, d0, d1))
    deltas.sort(key=lambda item: item[0], reverse=True)
    for delta, label, d0, d1 in deltas[:3]:
        if delta > 0.05:
            reasons.append(f"{label} の搬送距離が {d0:.1f} から {d1:.1f} に短縮")

    for rel in problem.relations:
        if rel.kind != "prefer":
            continue
        a0, b0 = init_by.get(rel.a), init_by.get(rel.b)
        a1, b1 = prop_by.get(rel.a), prop_by.get(rel.b)
        if a0 and b0 and a1 and b1 and share_edge(a1, b1) and not share_edge(a0, b0):
            reasons.append(
                f"{names.get(rel.a, rel.a)} と {names.get(rel.b, rel.b)} を隣接させた"
            )

    s0, s1 = evaluate(problem, initial), evaluate(problem, proposed)
    if s1.process_aligned and not s0.process_aligned:
        reasons.append("入庫から出庫が南方向に整列した")
    elif s1.process_aligned:
        reasons.append("入庫→製造→出庫の流れを維持している")
    else:
        reasons.append("物流は短いが、工程チェーンに逆行がある")
    if not reasons:
        reasons.append("ハード制約を満たす実行可能配置")
    return reasons


def exact_best_if_tractable(problem: LayoutProblem) -> float | None:
    """1x1 かつ敷地が小さいときだけ全列挙する。推測では埋めない。"""
    import itertools

    if any(d.width != 1 or d.height != 1 for d in problem.departments):
        return None
    if len(problem.departments) > 4 or problem.rows * problem.cols > 9:
        return None
    cells = [(r, c) for r in range(problem.rows) for c in range(problem.cols) if (r, c) not in set(problem.blocked)]
    if len(cells) < len(problem.departments):
        return None
    best = None
    for chosen in itertools.permutations(cells, len(problem.departments)):
        placements = [
            Placement(d.id, r, c, 1, 1)
            for d, (r, c) in zip(problem.departments, chosen, strict=True)
        ]
        score = evaluate(problem, placements)
        if score.feasible and (best is None or score.total < best):
            best = score.total
    return best


def process_summary(problem: LayoutProblem, placements: list[Placement]) -> str:
    names = {d.id: d.name for d in problem.departments}
    chain = problem.process_chain or [d.id for d in problem.departments if d.role in {"inbound", "process", "outbound"}]
    if not chain:
        return "工程チェーン未設定"
    by_id = _placements_by_id(placements)
    parts = [names.get(i, i) for i in chain if i in by_id]
    score = evaluate(problem, placements)
    suffix = "（南方向に整列）" if score.process_aligned else "（逆行あり）"
    return " → ".join(parts) + suffix


def _orientations(dept: Department) -> list[tuple[int, int]]:
    opts = [(dept.width, dept.height)]
    if dept.rotatable and dept.width != dept.height:
        opts.append((dept.height, dept.width))
    return opts


def _candidate_positions(
    problem: LayoutProblem, dept: Department, taken: set[tuple[int, int]]
) -> list[Placement]:
    blocked = set(problem.blocked)
    out: list[Placement] = []
    if dept.fixed_row is not None and dept.fixed_col is not None:
        for w, h in _orientations(dept):
            p = Placement(dept.id, dept.fixed_row, dept.fixed_col, w, h)
            cells = occupancy(p)
            if cells.isdisjoint(taken) and cells.isdisjoint(blocked):
                if 0 <= p.row and 0 <= p.col and p.row + h <= problem.rows and p.col + w <= problem.cols:
                    out.append(p)
        return out
    for w, h in _orientations(dept):
        for r in range(0, problem.rows - h + 1):
            for c in range(0, problem.cols - w + 1):
                p = Placement(dept.id, r, c, w, h)
                cells = occupancy(p)
                if cells.isdisjoint(taken) and cells.isdisjoint(blocked):
                    out.append(p)
    return out


def _order_departments(problem: LayoutProblem) -> list[Department]:
    flow_sum = {d.id: 0.0 for d in problem.departments}
    for fl in problem.flows:
        if fl.from_id in flow_sum:
            flow_sum[fl.from_id] += fl.volume
        if fl.to_id in flow_sum:
            flow_sum[fl.to_id] += fl.volume
    return sorted(
        problem.departments,
        key=lambda d: (0 if d.fixed_row is not None else 1, -flow_sum[d.id], d.id),
    )


def greedy_layout(
    problem: LayoutProblem,
    rng: random.Random | None = None,
    top_k: int = 1,
) -> list[Placement]:
    """物流量の大きい工程から、増分目的値が小さい位置へ置く。

    rng と top_k>1 のときは上位候補から選んで、異なる実行可能パターンを作る。
    """
    placed: list[Placement] = []
    taken: set[tuple[int, int]] = set()
    for dept in _order_departments(problem):
        scored: list[tuple[float, Placement]] = []
        for cand in _candidate_positions(problem, dept, taken):
            score = evaluate(problem, [*placed, cand])
            scored.append((score.total, cand))
        if not scored:
            raise OptimizerError(f"実行可能解なし: {dept.name} ({dept.id}) を置ける位置がありません")
        scored.sort(key=lambda item: item[0])
        pick = scored[0][1]
        if rng is not None and top_k > 1:
            best_val = scored[0][0]
            near = [c for v, c in scored[:top_k] if v <= best_val * 1.2 + 1.0]
            pick = rng.choice(near)
        placed.append(pick)
        taken |= occupancy(pick)
    score = evaluate(problem, placed)
    if not score.feasible:
        raise OptimizerError("実行可能解なし: " + " / ".join(score.violations))
    return placed


def _neighbors(problem: LayoutProblem, placements: list[Placement], rng: random.Random) -> list[list[Placement]]:
    """近傍: 非固定工程の再配置または回転。"""
    depts = _dept_map(problem)
    movable = [p for p in placements if depts[p.dept_id].fixed_row is None]
    if not movable:
        return []
    target = rng.choice(movable)
    others = [p for p in placements if p.dept_id != target.dept_id]
    taken = set()
    for p in others:
        taken |= occupancy(p)
    dept = depts[target.dept_id]
    cands = _candidate_positions(problem, dept, taken)
    rng.shuffle(cands)
    out: list[list[Placement]] = []
    for cand in cands[:40]:
        if cand.row == target.row and cand.col == target.col and cand.width == target.width:
            continue
        out.append([*others, cand])
    return out


def improve_layout(
    problem: LayoutProblem,
    initial: list[Placement],
    *,
    seed: int | None,
    max_passes: int,
    time_limit_ms: int | None,
    use_sa: bool,
) -> tuple[list[Placement], int, int, int]:
    rng = random.Random(seed)
    best = list(initial)
    best_score = evaluate(problem, best)
    current = list(best)
    current_score = best_score
    evaluations = 1
    accepted = 0
    passes = 0
    started = time.perf_counter()
    temperature = best_score.total * 0.15 if use_sa else 0.0

    while passes < max_passes:
        if time_limit_ms is not None and (time.perf_counter() - started) * 1000 >= time_limit_ms:
            break
        passes += 1
        neighbors = _neighbors(problem, current, rng)
        if not neighbors:
            break
        progressed = False
        for cand in neighbors:
            evaluations += 1
            score = evaluate(problem, cand)
            delta = score.total - current_score.total
            accept = delta < -1e-12
            if not accept and use_sa and temperature > 1e-9 and delta < HARD_INFEASIBLE / 2:
                accept = rng.random() < math.exp(-delta / temperature)
            if accept:
                current, current_score = cand, score
                accepted += 1
                progressed = True
                if score.total + 1e-12 < best_score.total:
                    best, best_score = list(cand), score
                break
        if use_sa:
            temperature *= 0.92
        elif not progressed:
            break
    return best, evaluations, accepted, passes


def _signature(placements: list[Placement]) -> tuple[tuple[str, int, int, int, int], ...]:
    return tuple(sorted((p.dept_id, p.row, p.col, p.width, p.height) for p in placements))


def optimize(
    problem: LayoutProblem,
    *,
    seed: int | None = None,
    max_passes: int = 80,
    time_limit_ms: int | None = None,
    n_proposals: int = 3,
) -> SearchResult:
    """複数スタートで条件を満たすレイアウト案を集める。最良案を代表として返す。"""
    _validate_problem(problem)
    n_proposals = max(1, min(n_proposals, 8))
    base_seed = 1 if seed is None else seed
    initial = greedy_layout(problem)
    proposals: list[LayoutProposal] = []
    seen: set[tuple[tuple[str, int, int, int, int], ...]] = set()
    evaluations = 0
    accepted = 0
    passes = 0
    best = list(initial)
    best_score = evaluate(problem, best)

    for i in range(n_proposals):
        run_seed = base_seed + i * 17
        start = greedy_layout(problem, rng=random.Random(run_seed), top_k=4)
        improved, ev, acc, pas = improve_layout(
            problem,
            start,
            seed=run_seed,
            max_passes=max_passes,
            time_limit_ms=time_limit_ms,
            use_sa=True,
        )
        evaluations += ev
        accepted += acc
        passes += pas
        score = evaluate(problem, improved)
        if not score.feasible:
            continue
        sig = _signature(improved)
        if sig in seen:
            continue
        seen.add(sig)
        if score.total + 1e-12 < best_score.total:
            best, best_score = list(improved), score
        proposals.append(
            LayoutProposal(
                rank=0,
                label="",
                placements=improved,
                score=score,
                seed_used=run_seed,
                process_summary=process_summary(problem, improved),
                reasons=tuple(explain_proposal(problem, initial, improved)),
                path=tuple(process_path(problem, improved)),
            )
        )

    if not proposals:
        raise OptimizerError("条件を満たすレイアウト案を作れませんでした")

    proposals.sort(key=lambda p: (p.score.process_penalty, p.score.total))
    ranked = [
        LayoutProposal(
            rank=i + 1,
            label=f"案{i + 1}",
            placements=p.placements,
            score=p.score,
            seed_used=p.seed_used,
            process_summary=p.process_summary,
            reasons=p.reasons,
            path=p.path,
        )
        for i, p in enumerate(proposals)
    ]
    s0 = evaluate(problem, initial)
    s1 = ranked[0].score
    best = ranked[0].placements
    improvement = s0.total - s1.total
    rate = (improvement / s0.total * 100.0) if s0.total > 0 else 0.0
    exact_best = exact_best_if_tractable(problem)
    gap = None if exact_best is None else max(0.0, s1.total - exact_best)
    note = "ヒューリスティックによる複数の実行可能案であり、厳密な最適解ではない"
    if exact_best is not None:
        note = f"小規模インスタンスで全列挙した厳密最良は {exact_best:.2f}。案1とのギャップは {gap:.2f}"
    return SearchResult(
        initial_placements=initial,
        best_placements=best,
        initial_score=s0,
        best_score=s1,
        improvement=improvement,
        improvement_rate=rate,
        evaluations=evaluations,
        accepted_moves=accepted,
        passes=passes,
        seed=seed,
        algorithm="multi-start greedy + SA（組み合わせ探索）",
        note=note,
        proposals=ranked,
        exact_best=exact_best,
        optimality_gap=gap,
    )


def _validate_problem(problem: LayoutProblem) -> None:
    if problem.rows < 1 or problem.cols < 1:
        raise OptimizerError("敷地サイズが不正です")
    if not problem.departments:
        raise OptimizerError("工程が空です")
    ids = [d.id for d in problem.departments]
    if any(not i.strip() for i in ids):
        raise OptimizerError("工程IDが空です")
    if len(set(ids)) != len(ids):
        raise OptimizerError("工程IDは重複できません")
    for d in problem.departments:
        if d.role not in ROLES:
            raise OptimizerError(f"{d.id} の役割は {', '.join(ROLES)} のいずれかです")
        if d.width < 1 or d.height < 1:
            raise OptimizerError(f"{d.id} の寸法が不正です")
        if d.width * d.height > problem.rows * problem.cols:
            raise OptimizerError(f"{d.id} が敷地より大きいです")
    if problem.process_chain:
        known_ids = set(ids)
        for step in problem.process_chain:
            if step not in known_ids:
                raise OptimizerError(f"工程チェーンに未知のIDがあります: {step}")
    known = set(ids)
    for fl in problem.flows:
        if fl.volume < 0:
            raise OptimizerError("物流量は0以上にしてください")
        if fl.from_id not in known or fl.to_id not in known:
            raise OptimizerError("物流の工程IDが存在しません")
    for rel in problem.relations:
        if rel.kind not in {"prefer", "forbid"}:
            raise OptimizerError("関係の種別は prefer または forbid です")
        if rel.a not in known or rel.b not in known:
            raise OptimizerError("関係の工程IDが存在しません")
    for r, c in problem.blocked:
        if not (0 <= r < problem.rows and 0 <= c < problem.cols):
            raise OptimizerError("禁止セルが敷地外です")


def grid_from_placements(problem: LayoutProblem, placements: list[Placement]) -> list[list[str]]:
    grid = [["blocked" if (r, c) in set(problem.blocked) else "" for c in range(problem.cols)] for r in range(problem.rows)]
    for p in placements:
        for r, c in occupancy(p):
            if 0 <= r < problem.rows and 0 <= c < problem.cols:
                grid[r][c] = p.dept_id
    return grid


def sample_factory() -> LayoutProblem:
    """中規模組立工場の建設レイアウト PoC 用サンプル。"""
    return LayoutProblem(
        rows=10,
        cols=12,
        departments=[
            Department("recv", "受入・原材料", 3, 2, role="inbound"),
            Department("mach", "機械加工", 4, 3, role="process"),
            Department("assy", "組立", 4, 3, role="process"),
            Department("insp", "検査", 2, 2, role="process"),
            Department("ship", "出荷場", 3, 2, fixed_row=8, fixed_col=0, rotatable=False, role="outbound"),
            Department("office", "事務所", 2, 2, role="support"),
            Department("haz", "危険物庫", 2, 2, role="support"),
        ],
        process_chain=["recv", "mach", "assy", "insp", "ship"],
        process_weight=12.0,
        flows=[
            Flow("recv", "mach", 80),
            Flow("mach", "assy", 70),
            Flow("assy", "insp", 50),
            Flow("insp", "ship", 45),
            Flow("recv", "ship", 8),
            Flow("office", "insp", 10),
            Flow("haz", "mach", 15),
        ],
        relations=[
            Relation("insp", "ship", "prefer"),
            Relation("recv", "mach", "prefer"),
            Relation("haz", "office", "forbid", min_cell_distance=3),
        ],
        blocked=[(4, 5), (4, 6), (5, 5), (5, 6)],
        adjacency_weight=8.0,
    )
