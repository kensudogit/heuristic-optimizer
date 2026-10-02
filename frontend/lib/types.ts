export type Department = {
  id: string;
  name: string;
  width: number;
  height: number;
  fixed_row: number | null;
  fixed_col: number | null;
  rotatable: boolean;
  role: "inbound" | "process" | "outbound" | "support";
};

export type Flow = {
  from_id: string;
  to_id: string;
  volume: number;
};

export type Relation = {
  a: string;
  b: string;
  kind: "prefer" | "forbid";
  min_cell_distance: number;
};

export type Cell = {
  row: number;
  col: number;
};

export type Placement = {
  dept_id: string;
  name: string;
  row: number;
  col: number;
  width: number;
  height: number;
};

export type Score = {
  total: number;
  flow_cost: number;
  adjacency_penalty: number;
  process_penalty: number;
  process_aligned: boolean;
  feasible: boolean;
  violations: string[];
};

export type OptimizeRequest = {
  rows: number;
  cols: number;
  departments: Department[];
  flows: Flow[];
  relations: Relation[];
  blocked: Cell[];
  adjacency_weight: number;
  process_chain: string[];
  process_weight: number;
  n_proposals: number;
  seed: number | null;
  max_passes: number;
  time_limit_ms?: number | null;
};

export type OptimizeResponse = {
  initial_placements: Placement[];
  best_placements: Placement[];
  initial_grid: string[][];
  best_grid: string[][];
  initial_score: Score;
  best_score: Score;
  improvement: number;
  improvement_rate: number;
  evaluations: number;
  accepted_moves: number;
  passes: number;
  seed: number | null;
  algorithm: string;
  note: string;
  proposals: Proposal[];
  exact_best: number | null;
  optimality_gap: number | null;
};

export type PathPoint = {
  row: number;
  col: number;
};

export type Proposal = {
  rank: number;
  label: string;
  placements: Placement[];
  grid: string[][];
  score: Score;
  seed_used: number;
  process_summary: string;
  reasons: string[];
  path: PathPoint[];
};

export type ApiErrorBody = {
  detail?: string | { msg?: string }[];
};
