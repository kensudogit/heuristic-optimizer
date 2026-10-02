"""工場レイアウト最適化APIの入出力。探索ロジックは含まない。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DepartmentIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=80)
    width: int = Field(ge=1, le=40)
    height: int = Field(ge=1, le=40)
    fixed_row: int | None = Field(default=None, ge=0)
    fixed_col: int | None = Field(default=None, ge=0)
    rotatable: bool = True
    role: str = Field(default="process", pattern="^(inbound|process|outbound|support)$")


class FlowIn(BaseModel):
    from_id: str = Field(min_length=1, max_length=32)
    to_id: str = Field(min_length=1, max_length=32)
    volume: float = Field(ge=0)


class RelationIn(BaseModel):
    a: str = Field(min_length=1, max_length=32)
    b: str = Field(min_length=1, max_length=32)
    kind: str = Field(pattern="^(prefer|forbid)$")
    min_cell_distance: int = Field(default=0, ge=0, le=80)


class CellIn(BaseModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)


class PlacementOut(BaseModel):
    dept_id: str
    name: str
    row: int
    col: int
    width: int
    height: int


class ScoreOut(BaseModel):
    total: float
    flow_cost: float
    adjacency_penalty: float
    process_penalty: float
    process_aligned: bool
    feasible: bool
    violations: list[str]


class OptimizeRequest(BaseModel):
    rows: int = Field(ge=2, le=40)
    cols: int = Field(ge=2, le=40)
    departments: list[DepartmentIn] = Field(min_length=1)
    flows: list[FlowIn] = Field(default_factory=list)
    relations: list[RelationIn] = Field(default_factory=list)
    blocked: list[CellIn] = Field(default_factory=list)
    adjacency_weight: float = Field(default=8.0, ge=0, le=1000)
    process_chain: list[str] = Field(default_factory=list)
    process_weight: float = Field(default=12.0, ge=0, le=1000)
    n_proposals: int = Field(default=3, ge=1, le=8)
    seed: int | None = None
    max_passes: int = Field(default=80, ge=1, le=2000)
    time_limit_ms: int | None = Field(default=None, ge=1, le=120_000)
    exact: bool = True


class PathPointOut(BaseModel):
    row: float
    col: float


class ProposalOut(BaseModel):
    rank: int
    label: str
    placements: list[PlacementOut]
    grid: list[list[str]]
    score: ScoreOut
    seed_used: int
    process_summary: str
    reasons: list[str]
    path: list[PathPointOut]


class EffectivenessOut(BaseModel):
    lower_bound: float
    estimated_gap: float
    estimated_gap_rate: float
    adjacency_hits: int
    adjacency_total: int
    aligned_proposals: int
    proposal_count: int
    utilization: float


class OptimizeResponse(BaseModel):
    initial_placements: list[PlacementOut]
    best_placements: list[PlacementOut]
    initial_grid: list[list[str]]
    best_grid: list[list[str]]
    initial_score: ScoreOut
    best_score: ScoreOut
    improvement: float
    improvement_rate: float
    evaluations: int
    accepted_moves: int
    passes: int
    seed: int | None
    algorithm: str
    note: str
    proposals: list[ProposalOut]
    exact_best: float | None = None
    optimality_gap: float | None = None
    effectiveness: EffectivenessOut | None = None
    optimal: bool = False
