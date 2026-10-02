"""工場建設レイアウト（施設配置）のヒューリスティック探索。

問題: 敷地グリッド上に建屋・工程を重ねずに配置する。
目的: 物流量 × 重心間マンハッタン距離 + 隣接希望の未達ペナルティ を最小化。
      exact=True のときは CP-SAT で厳密最適を求め、証明できたときだけ最適と書く。
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
class Effectiveness:
    """ヒューリスティック案の品質。下界は他棟競合を無視した物流費用。"""

    lower_bound: float
    estimated_gap: float
    estimated_gap_rate: float
    adjacency_hits: int
    adjacency_total: int
    aligned_proposals: int
    proposal_count: int
    utilization: float


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
    effectiveness: Effectiveness | None = None
    optimal: bool = False


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


def _in_bounds(problem: LayoutProblem, p: Placement) -> bool:
    return 0 <= p.row and 0 <= p.col and p.row + p.height <= problem.rows and p.col + p.width <= problem.cols


def _chain_guide_penalty(problem: LayoutProblem, dept: Department, cand: Placement) -> float:
    """工程チェーン上の棟を、北→南の帯に寄せる。評価関数ではなく貪欲の誘導だけに使う。"""
    chain = problem.process_chain
    if dept.id not in chain or len(chain) < 2:
        return 0.0
    idx = chain.index(dept.id)
    target = idx / (len(chain) - 1) * max(0, problem.rows - cand.height)
    return problem.process_weight * abs(cand.row - target) * 0.4


def flow_lower_bound(problem: LayoutProblem) -> float:
    """各物流を2棟だけで最短配置した費用の合計。他棟との競合は無視するので下界。"""
    depts = _dept_map(problem)
    total = 0.0
    for fl in problem.flows:
        da, db = depts.get(fl.from_id), depts.get(fl.to_id)
        if not da or not db:
            continue
        best: float | None = None
        for pa in _candidate_positions(problem, da, set()):
            taken = occupancy(pa)
            for pb in _candidate_positions(problem, db, taken):
                dist = manhattan(centroid(pa), centroid(pb))
                if best is None or dist < best:
                    best = dist
                    if best == 0.0:
                        break
            if best == 0.0:
                break
        if best is not None:
            total += fl.volume * best
    return total


def adjacency_hit_count(problem: LayoutProblem, placements: list[Placement]) -> tuple[int, int]:
    by_id = _placements_by_id(placements)
    hits = 0
    total = 0
    for rel in problem.relations:
        if rel.kind != "prefer":
            continue
        total += 1
        pa, pb = by_id.get(rel.a), by_id.get(rel.b)
        if pa and pb and share_edge(pa, pb):
            hits += 1
    return hits, total


def site_utilization(problem: LayoutProblem, placements: list[Placement]) -> float:
    usable = problem.rows * problem.cols - len(set(problem.blocked))
    if usable <= 0:
        return 0.0
    occupied = set()
    for p in placements:
        occupied |= occupancy(p)
    return len(occupied) / usable


def measure_effectiveness(
    problem: LayoutProblem,
    best: list[Placement],
    best_score: Score,
    proposals: list[LayoutProposal],
) -> Effectiveness:
    lower = flow_lower_bound(problem)
    gap = max(0.0, best_score.flow_cost - lower)
    rate = (gap / best_score.flow_cost * 100.0) if best_score.flow_cost > 0 else 0.0
    hits, adj_total = adjacency_hit_count(problem, best)
    return Effectiveness(
        lower_bound=lower,
        estimated_gap=gap,
        estimated_gap_rate=rate,
        adjacency_hits=hits,
        adjacency_total=adj_total,
        aligned_proposals=sum(1 for p in proposals if p.score.process_aligned),
        proposal_count=len(proposals),
        utilization=site_utilization(problem, best),
    )


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
            if cells.isdisjoint(taken) and cells.isdisjoint(blocked) and _in_bounds(problem, p):
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
            scored.append((score.total + _chain_guide_penalty(problem, dept, cand), cand))
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


def _swap_neighbors(problem: LayoutProblem, placements: list[Placement]) -> list[list[Placement]]:
    """寸法が違う棟でも、互いの左上に置き直せるなら交換する。"""
    depts = _dept_map(problem)
    movable = [p for p in placements if depts[p.dept_id].fixed_row is None]
    blocked = set(problem.blocked)
    out: list[list[Placement]] = []
    for i, a in enumerate(movable):
        for b in movable[i + 1 :]:
            others = [p for p in placements if p.dept_id not in {a.dept_id, b.dept_id}]
            taken: set[tuple[int, int]] = set()
            for p in others:
                taken |= occupancy(p)
            pa = Placement(a.dept_id, b.row, b.col, a.width, a.height)
            pb = Placement(b.dept_id, a.row, a.col, b.width, b.height)
            cells_a, cells_b = occupancy(pa), occupancy(pb)
            if not _in_bounds(problem, pa) or not _in_bounds(problem, pb):
                continue
            if cells_a & cells_b or cells_a & taken or cells_b & taken:
                continue
            if cells_a & blocked or cells_b & blocked:
                continue
            out.append([*others, pa, pb])
            if len(out) >= 12:
                return out
    return out


def _align_neighbors(problem: LayoutProblem, placements: list[Placement]) -> list[list[Placement]]:
    """逆行している工程を、より南（または北）へ動かしてチェーンを直す。"""
    chain = problem.process_chain
    if len(chain) < 2:
        return []
    depts = _dept_map(problem)
    by_id = _placements_by_id(placements)
    blocked = set(problem.blocked)
    out: list[list[Placement]] = []
    for prev_id, next_id in zip(chain, chain[1:], strict=False):
        pa, pb = by_id.get(prev_id), by_id.get(next_id)
        if not pa or not pb:
            continue
        if centroid(pb)[0] + 0.25 >= centroid(pa)[0]:
            continue
        moving = pb if depts[next_id].fixed_row is None else pa if depts[prev_id].fixed_row is None else None
        if moving is None:
            continue
        anchor = pa if moving.dept_id == pb.dept_id else pb
        others = [p for p in placements if p.dept_id != moving.dept_id]
        taken: set[tuple[int, int]] = set()
        for p in others:
            taken |= occupancy(p)
        for cand in _candidate_positions(problem, depts[moving.dept_id], taken):
            if occupancy(cand) & blocked:
                continue
            south_ok = moving.dept_id == pb.dept_id and centroid(cand)[0] + 0.25 >= centroid(anchor)[0]
            north_ok = moving.dept_id == pa.dept_id and centroid(anchor)[0] + 0.25 >= centroid(cand)[0]
            if south_ok or north_ok:
                out.append([*others, cand])
                if len(out) >= 8:
                    return out
    return out


def _neighbors(problem: LayoutProblem, placements: list[Placement], rng: random.Random) -> list[list[Placement]]:
    """近傍: 逆行修正、2棟交換、非固定工程の再配置・回転。"""
    depts = _dept_map(problem)
    movable = [p for p in placements if depts[p.dept_id].fixed_row is None]
    out = _align_neighbors(problem, placements) + _swap_neighbors(problem, placements)
    if not movable:
        return out
    target = rng.choice(movable)
    others = [p for p in placements if p.dept_id != target.dept_id]
    taken = set()
    for p in others:
        taken |= occupancy(p)
    dept = depts[target.dept_id]
    cands = _candidate_positions(problem, dept, taken)
    rng.shuffle(cands)
    for cand in cands[:32]:
        if cand.row == target.row and cand.col == target.col and cand.width == target.width:
            continue
        out.append([*others, cand])
    return out[:48]


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
    exact: bool = False,
) -> SearchResult:
    """ヒューリスティック、または exact=True なら CP-SAT の厳密最適を返す。"""
    _validate_problem(problem)
    if exact:
        return _optimize_exact(problem, seed=seed, max_passes=max_passes, time_limit_ms=time_limit_ms, n_proposals=n_proposals)
    n_proposals = max(1, min(n_proposals, 8))
    n_starts = min(12, max(n_proposals * 3, n_proposals))
    base_seed = 1 if seed is None else seed
    initial = greedy_layout(problem)
    proposals: list[LayoutProposal] = []
    seen: set[tuple[tuple[str, int, int, int, int], ...]] = set()
    evaluations = 0
    accepted = 0
    passes = 0

    for i in range(n_starts):
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

    selected = _select_diverse(proposals, n_proposals)
    selected.sort(key=lambda p: (p.score.process_penalty, p.score.total))
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
        for i, p in enumerate(selected)
    ]
    s0 = evaluate(problem, initial)
    s1 = ranked[0].score
    best = ranked[0].placements
    improvement = s0.total - s1.total
    rate = (improvement / s0.total * 100.0) if s0.total > 0 else 0.0
    exact_best = exact_best_if_tractable(problem)
    gap = None if exact_best is None else max(0.0, s1.total - exact_best)
    quality = measure_effectiveness(problem, best, s1, ranked)
    note = "ヒューリスティックによる複数の実行可能案であり、厳密な最適解ではない"
    if exact_best is not None:
        note = f"小規模インスタンスで全列挙した厳密最良は {exact_best:.2f}。案1とのギャップは {gap:.2f}"
    else:
        note = (
            f"{note}。物流下界 {quality.lower_bound:.1f} に対する推定ギャップは "
            f"{quality.estimated_gap:.1f}（{quality.estimated_gap_rate:.1f}%）"
        )
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
        algorithm="chain-guided multi-start + swap/SA",
        note=note,
        proposals=ranked,
        exact_best=exact_best,
        optimality_gap=gap,
        effectiveness=quality,
        optimal=exact_best is not None and gap == 0.0,
    )


def _optimize_exact(
    problem: LayoutProblem,
    *,
    seed: int | None,
    max_passes: int,
    time_limit_ms: int | None,
    n_proposals: int,
) -> SearchResult:
    from app.services.exact import solve_exact

    n_proposals = max(1, min(n_proposals, 8))
    initial = greedy_layout(problem)
    s0 = evaluate(problem, initial)
    exact = solve_exact(problem, time_limit_ms=time_limit_ms or 45_000, hint=initial)
    extra: list[LayoutProposal] = []
    proposals = [
        LayoutProposal(
            rank=1,
            label="最適解" if exact.proven else "厳密最良（未証明）",
            placements=exact.placements,
            score=exact.score,
            seed_used=seed if seed is not None else 0,
            process_summary=process_summary(problem, exact.placements),
            reasons=tuple(explain_proposal(problem, initial, exact.placements)),
            path=tuple(process_path(problem, exact.placements)),
        )
    ]
    seen = {_signature(exact.placements)}
    for item in extra:
        if _signature(item.placements) in seen:
            continue
        seen.add(_signature(item.placements))
        proposals.append(
            LayoutProposal(
                rank=len(proposals) + 1,
                label=f"参考案{len(proposals)}（ヒューリスティック）",
                placements=item.placements,
                score=item.score,
                seed_used=item.seed_used,
                process_summary=item.process_summary,
                reasons=item.reasons,
                path=item.path,
            )
        )
        if len(proposals) >= n_proposals:
            break
    improvement = s0.total - exact.score.total
    rate = (improvement / s0.total * 100.0) if s0.total > 0 else 0.0
    quality = measure_effectiveness(problem, exact.placements, exact.score, proposals)
    if exact.proven:
        quality = Effectiveness(
            lower_bound=exact.score.total,
            estimated_gap=0.0,
            estimated_gap_rate=0.0,
            adjacency_hits=quality.adjacency_hits,
            adjacency_total=quality.adjacency_total,
            aligned_proposals=quality.aligned_proposals,
            proposal_count=quality.proposal_count,
            utilization=quality.utilization,
        )
        note = f"分枝限定が目的関数 {exact.score.total:.2f} の厳密最適を証明しました"
        exact_best = exact.score.total
        gap = 0.0
    else:
        bound = exact.objective_bound
        gap = None if bound is None else max(0.0, exact.score.total - bound)
        exact_best = bound
        note = (
            f"制限時間内の最良解 {exact.score.total:.2f}。最適性は未証明"
            + (f"（下界 {bound:.2f}）" if bound is not None else "")
        )
    return SearchResult(
        initial_placements=initial,
        best_placements=exact.placements,
        initial_score=s0,
        best_score=exact.score,
        improvement=improvement,
        improvement_rate=rate,
        evaluations=exact.branches,
        accepted_moves=1 if exact.proven else 0,
        passes=1,
        seed=seed,
        algorithm="分枝限定（厳密最適化）" if exact.proven else "分枝限定（時間切れ・未証明）",
        note=note,
        proposals=proposals,
        exact_best=exact_best,
        optimality_gap=gap,
        effectiveness=quality,
        optimal=exact.proven,
    )


def _placement_hamming(a: list[Placement], b: list[Placement]) -> int:
    ba, bb = _placements_by_id(a), _placements_by_id(b)
    return sum(
        1
        for dept_id, pa in ba.items()
        if dept_id not in bb or (pa.row, pa.col, pa.width, pa.height) != (bb[dept_id].row, bb[dept_id].col, bb[dept_id].width, bb[dept_id].height)
    )


def _select_diverse(proposals: list[LayoutProposal], n: int) -> list[LayoutProposal]:
    """整列案を優先しつつ、配置の違う案を残す。"""
    if len(proposals) <= n:
        return list(proposals)
    aligned = [p for p in proposals if p.score.process_aligned]
    pool = list(proposals)
    selected: list[LayoutProposal] = []
    if aligned:
        selected.append(min(aligned, key=lambda p: p.score.total))
    while len(selected) < n and pool:
        selected_sigs = {_signature(p.placements) for p in selected}

        def key(p: LayoutProposal) -> tuple[float, float, float]:
            if _signature(p.placements) in selected_sigs:
                return (-1e18, 0.0, 0.0)
            dist = min((_placement_hamming(p.placements, s.placements) for s in selected), default=0)
            return (float(dist), -p.score.process_penalty, -p.score.total)

        pick = max(pool, key=key)
        if _signature(pick.placements) in selected_sigs:
            break
        selected.append(pick)
        pool = [p for p in pool if _signature(p.placements) != _signature(pick.placements)]
    return selected[:n]


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
