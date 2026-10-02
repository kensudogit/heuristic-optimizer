"""FastAPI 入口。探索本体は services.optimizer に置く。"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    CellIn,
    DepartmentIn,
    EffectivenessOut,
    FlowIn,
    OptimizeRequest,
    OptimizeResponse,
    PathPointOut,
    PlacementOut,
    ProposalOut,
    RelationIn,
    ScoreOut,
)
from app.services.optimizer import (
    Department,
    Flow,
    LayoutProblem,
    OptimizerError,
    Placement,
    Relation,
    SearchResult,
    grid_from_placements,
    optimize,
    sample_factory,
)

app = FastAPI(
    title="Factory Layout Optimizer",
    version="1.0.0",
    description="工場建設レイアウトのヒューリスティック探索。返るのは最良近似解。",
)

_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:3010").split(",")
    if origin.strip()
]
_allow_all = "*" in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _origins,
    allow_credentials=not _allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_problem(req: OptimizeRequest) -> LayoutProblem:
    return LayoutProblem(
        rows=req.rows,
        cols=req.cols,
        departments=[
            Department(
                id=d.id.strip(),
                name=d.name.strip(),
                width=d.width,
                height=d.height,
                fixed_row=d.fixed_row,
                fixed_col=d.fixed_col,
                rotatable=d.rotatable,
                role=d.role,
            )
            for d in req.departments
        ],
        flows=[Flow(f.from_id.strip(), f.to_id.strip(), f.volume) for f in req.flows],
        relations=[
            Relation(r.a.strip(), r.b.strip(), r.kind, r.min_cell_distance) for r in req.relations
        ],
        blocked=[(c.row, c.col) for c in req.blocked],
        adjacency_weight=req.adjacency_weight,
        process_chain=[step.strip() for step in req.process_chain if step.strip()],
        process_weight=req.process_weight,
    )


def _placement_out(problem: LayoutProblem, p: Placement) -> PlacementOut:
    names = {d.id: d.name for d in problem.departments}
    return PlacementOut(
        dept_id=p.dept_id,
        name=names.get(p.dept_id, p.dept_id),
        row=p.row,
        col=p.col,
        width=p.width,
        height=p.height,
    )


def _score_out(score) -> ScoreOut:
    return ScoreOut(
        total=round(score.total, 4),
        flow_cost=round(score.flow_cost, 4),
        adjacency_penalty=round(score.adjacency_penalty, 4),
        process_penalty=round(score.process_penalty, 4),
        process_aligned=score.process_aligned,
        feasible=score.feasible,
        violations=list(score.violations),
    )


def _effectiveness_out(quality) -> EffectivenessOut | None:
    if quality is None:
        return None
    return EffectivenessOut(
        lower_bound=round(quality.lower_bound, 4),
        estimated_gap=round(quality.estimated_gap, 4),
        estimated_gap_rate=round(quality.estimated_gap_rate, 2),
        adjacency_hits=quality.adjacency_hits,
        adjacency_total=quality.adjacency_total,
        aligned_proposals=quality.aligned_proposals,
        proposal_count=quality.proposal_count,
        utilization=round(quality.utilization, 4),
    )


def _to_response(problem: LayoutProblem, result: SearchResult) -> OptimizeResponse:
    return OptimizeResponse(
        initial_placements=[_placement_out(problem, p) for p in result.initial_placements],
        best_placements=[_placement_out(problem, p) for p in result.best_placements],
        initial_grid=grid_from_placements(problem, result.initial_placements),
        best_grid=grid_from_placements(problem, result.best_placements),
        initial_score=_score_out(result.initial_score),
        best_score=_score_out(result.best_score),
        improvement=round(result.improvement, 4),
        improvement_rate=round(result.improvement_rate, 2),
        evaluations=result.evaluations,
        accepted_moves=result.accepted_moves,
        passes=result.passes,
        seed=result.seed,
        algorithm=result.algorithm,
        note=result.note,
        exact_best=None if result.exact_best is None else round(result.exact_best, 4),
        optimality_gap=None if result.optimality_gap is None else round(result.optimality_gap, 4),
        effectiveness=_effectiveness_out(result.effectiveness),
        optimal=result.optimal,
        proposals=[
            ProposalOut(
                rank=p.rank,
                label=p.label,
                placements=[_placement_out(problem, pl) for pl in p.placements],
                grid=grid_from_placements(problem, p.placements),
                score=_score_out(p.score),
                seed_used=p.seed_used,
                process_summary=p.process_summary,
                reasons=list(p.reasons),
                path=[PathPointOut(row=row, col=col) for row, col in p.path],
            )
            for p in result.proposals
        ],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sample", response_model=OptimizeRequest)
def sample() -> OptimizeRequest:
    problem = sample_factory()
    return OptimizeRequest(
        rows=problem.rows,
        cols=problem.cols,
        departments=[
            DepartmentIn(
                id=d.id,
                name=d.name,
                width=d.width,
                height=d.height,
                fixed_row=d.fixed_row,
                fixed_col=d.fixed_col,
                rotatable=d.rotatable,
                role=d.role,
            )
            for d in problem.departments
        ],
        process_chain=list(problem.process_chain),
        process_weight=problem.process_weight,
        n_proposals=3,
        flows=[FlowIn(from_id=f.from_id, to_id=f.to_id, volume=f.volume) for f in problem.flows],
        relations=[
            RelationIn(a=r.a, b=r.b, kind=r.kind, min_cell_distance=r.min_cell_distance)
            for r in problem.relations
        ],
        blocked=[CellIn(row=r, col=c) for r, c in problem.blocked],
        adjacency_weight=problem.adjacency_weight,
        seed=1,
        max_passes=80,
        exact=True,
        time_limit_ms=45_000,
    )


@app.post("/optimize", response_model=OptimizeResponse)
def optimize_layout(req: OptimizeRequest) -> OptimizeResponse:
    problem = _to_problem(req)
    try:
        result = optimize(
            problem,
            seed=req.seed,
            max_passes=req.max_passes,
            time_limit_ms=req.time_limit_ms,
            n_proposals=req.n_proposals,
            exact=req.exact,
        )
    except OptimizerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(problem, result)
