"use client";

import { useEffect, useState } from "react";
import { FactoryGrid } from "@/components/FactoryGrid";
import { GuideButton } from "@/components/GuideModal";
import { fetchSample, optimize } from "@/lib/api";
import type { Department, Flow, OptimizeRequest, OptimizeResponse, Proposal, Relation } from "@/lib/types";

const FALLBACK: OptimizeRequest = {
  rows: 10,
  cols: 12,
  departments: [
    { id: "recv", name: "受入・原材料", width: 3, height: 2, fixed_row: null, fixed_col: null, rotatable: true, role: "inbound" },
    { id: "mach", name: "機械加工", width: 4, height: 3, fixed_row: null, fixed_col: null, rotatable: true, role: "process" },
    { id: "assy", name: "組立", width: 4, height: 3, fixed_row: null, fixed_col: null, rotatable: true, role: "process" },
    { id: "insp", name: "検査", width: 2, height: 2, fixed_row: null, fixed_col: null, rotatable: true, role: "process" },
    { id: "ship", name: "出荷場", width: 3, height: 2, fixed_row: 8, fixed_col: 0, rotatable: false, role: "outbound" },
    { id: "office", name: "事務所", width: 2, height: 2, fixed_row: null, fixed_col: null, rotatable: true, role: "support" },
    { id: "haz", name: "危険物庫", width: 2, height: 2, fixed_row: null, fixed_col: null, rotatable: true, role: "support" },
  ],
  process_chain: ["recv", "mach", "assy", "insp", "ship"],
  process_weight: 12,
  n_proposals: 3,
  flows: [
    { from_id: "recv", to_id: "mach", volume: 80 },
    { from_id: "mach", to_id: "assy", volume: 70 },
    { from_id: "assy", to_id: "insp", volume: 50 },
    { from_id: "insp", to_id: "ship", volume: 45 },
    { from_id: "recv", to_id: "ship", volume: 8 },
    { from_id: "office", to_id: "insp", volume: 10 },
    { from_id: "haz", to_id: "mach", volume: 15 },
  ],
  relations: [
    { a: "insp", b: "ship", kind: "prefer", min_cell_distance: 0 },
    { a: "recv", b: "mach", kind: "prefer", min_cell_distance: 0 },
    { a: "haz", b: "office", kind: "forbid", min_cell_distance: 3 },
  ],
  blocked: [
    { row: 4, col: 5 },
    { row: 4, col: 6 },
    { row: 5, col: 5 },
    { row: 5, col: 6 },
  ],
  adjacency_weight: 8,
  seed: 1,
  max_passes: 80,
  exact: true,
  time_limit_ms: 45000,
};

export default function HomePage() {
  const [req, setReq] = useState<OptimizeRequest>(FALLBACK);
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetchSample()
      .then(setReq)
      .catch(() => undefined);
  }, []);

  const updateDept = (index: number, patch: Partial<Department>) => {
    setReq((current) => ({
      ...current,
      departments: current.departments.map((d, i) => (i === index ? { ...d, ...patch } : d)),
    }));
  };

  const updateFlow = (index: number, patch: Partial<Flow>) => {
    setReq((current) => ({
      ...current,
      flows: current.flows.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    }));
  };

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await optimize(req);
      setResult(data);
      setSelected(0);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "最適化に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      <div className="app-bar">
        <span className="app-bar-accent" aria-hidden="true" />
        <div className="app-bar-text">
          <p className="app-eyebrow">FACTORY LAYOUT</p>
          <h1>工場建設レイアウト最適化 PoC</h1>
          <p className="lead">
            建設業向けの工場レイアウト組み合わせ探索です。入庫→製造→出庫の流れと、敷地・離隔・隣接の条件を満たす
            配置を求めます。厳密モードでは分枝限定が最適性を証明した解だけを「最適解」と表示します。
          </p>
        </div>
        <GuideButton />
      </div>

      <section>
        <h2>敷地と探索条件</h2>
        <div className="controls">
          <label>
            行（南北）
            <input
              type="number"
              size={3}
              value={req.rows}
              onChange={(e) => setReq({ ...req, rows: Number(e.target.value) || 2 })}
            />
          </label>
          <label>
            列（東西）
            <input
              type="number"
              size={3}
              value={req.cols}
              onChange={(e) => setReq({ ...req, cols: Number(e.target.value) || 2 })}
            />
          </label>
          <label>
            seed
            <input
              size={4}
              value={req.seed ?? ""}
              onChange={(e) => setReq({ ...req, seed: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </label>
          <label>
            最大改善周回
            <input
              type="number"
              size={4}
              value={req.max_passes}
              onChange={(e) => setReq({ ...req, max_passes: Math.max(1, Number(e.target.value) || 80) })}
            />
          </label>
          <label>
            提案数
            <input
              type="number"
              size={2}
              value={req.n_proposals}
              onChange={(e) => setReq({ ...req, n_proposals: Math.min(8, Math.max(1, Number(e.target.value) || 3)) })}
            />
          </label>
          <label>
            制限時間（秒）
            <input
              type="number"
              size={3}
              min={1}
              max={120}
              value={Math.round((req.time_limit_ms ?? 45000) / 1000)}
              onChange={(e) =>
                setReq({
                  ...req,
                  time_limit_ms: Math.min(120000, Math.max(1000, (Number(e.target.value) || 45) * 1000)),
                })
              }
            />
          </label>
          <label className="exact-toggle">
            <input
              type="checkbox"
              checked={req.exact}
              onChange={(e) => setReq({ ...req, exact: e.target.checked })}
            />
            厳密最適
          </label>
        </div>
        <p className="note">
          工程チェーン: {req.process_chain.join(" → ") || "未設定"}。中央 2×2 は通路。出荷場は南側固定。
        </p>
      </section>

      <section>
        <h2>工程・建屋</h2>
        <div className="row dept head" aria-hidden="true">
          <span>工程ID</span>
          <span>名称</span>
          <span>役割</span>
          <span>幅</span>
          <span>高さ</span>
        </div>
        {req.departments.map((d, i) => (
          <div className="row dept" key={d.id}>
            <input size={8} value={d.id} onChange={(e) => updateDept(i, { id: e.target.value })} aria-label={`工程ID-${i}`} />
            <input size={12} value={d.name} onChange={(e) => updateDept(i, { name: e.target.value })} aria-label={`工程名-${i}`} />
            <select
              value={d.role}
              onChange={(e) => updateDept(i, { role: e.target.value as Department["role"] })}
              aria-label={`役割-${i}`}
            >
              <option value="inbound">入庫</option>
              <option value="process">製造</option>
              <option value="outbound">出庫</option>
              <option value="support">付帯</option>
            </select>
            <input
              type="number"
              size={3}
              value={d.width}
              onChange={(e) => updateDept(i, { width: Number(e.target.value) || 1 })}
              aria-label={`幅-${i}`}
            />
            <input
              type="number"
              size={3}
              value={d.height}
              onChange={(e) => updateDept(i, { height: Number(e.target.value) || 1 })}
              aria-label={`高さ-${i}`}
            />
          </div>
        ))}
      </section>

      <section>
        <h2>物流（パレット相当 / 日）</h2>
        <div className="row flow head" aria-hidden="true">
          <span>from</span>
          <span>to</span>
          <span>量</span>
        </div>
        {req.flows.map((f, i) => (
          <div className="row flow" key={`${f.from_id}-${f.to_id}-${i}`}>
            <input size={8} value={f.from_id} onChange={(e) => updateFlow(i, { from_id: e.target.value })} />
            <input size={8} value={f.to_id} onChange={(e) => updateFlow(i, { to_id: e.target.value })} />
            <input
              type="number"
              size={4}
              value={f.volume}
              onChange={(e) => updateFlow(i, { volume: Number(e.target.value) || 0 })}
            />
          </div>
        ))}
        <RelationList relations={req.relations} />
        <div className="actions">
          <button type="button" className="primary" onClick={() => void run()} disabled={loading}>
            {loading ? "探索中…" : "レイアウト探索"}
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </section>

      {result ? (
        <Results
          result={result}
          departments={req.departments}
          selected={selected}
          onSelect={setSelected}
        />
      ) : null}
    </main>
  );
}

function Results({
  result,
  departments,
  selected,
  onSelect,
}: {
  result: OptimizeResponse;
  departments: Department[];
  selected: number;
  onSelect: (index: number) => void;
}) {
  const proposal: Proposal | undefined = result.proposals[selected] ?? result.proposals[0];
  if (!proposal) return null;
  return (
    <section>
      <h2>提案レイアウト（{result.proposals.length}案）{result.optimal ? " · 厳密最適" : ""}</h2>
      <p className="note">{result.note}</p>
      {result.exact_best != null ? (
        <p className="note">
          厳密最良 {result.exact_best} / ギャップ {result.optimality_gap ?? 0}
        </p>
      ) : null}
      {result.effectiveness ? (
        <p className="note">
          物流下界 {result.effectiveness.lower_bound} / 推定ギャップ {result.effectiveness.estimated_gap}（
          {result.effectiveness.estimated_gap_rate}%） / 隣接 {result.effectiveness.adjacency_hits}/
          {result.effectiveness.adjacency_total} / 整列案 {result.effectiveness.aligned_proposals}/
          {result.effectiveness.proposal_count} / 敷地利用率{" "}
          {(result.effectiveness.utilization * 100).toFixed(1)}%
        </p>
      ) : null}
      <div className="actions">
        {result.proposals.map((item, index) => (
          <button
            key={item.label}
            type="button"
            className={index === selected ? "primary" : undefined}
            onClick={() => onSelect(index)}
          >
            {item.label}（{item.score.total}）
          </button>
        ))}
      </div>
      <div className="cards">
        <article>
          <b>初期費用</b>
          <span>{result.initial_score.total}</span>
        </article>
        <article>
          <b>{proposal.label} 費用</b>
          <span>{proposal.score.total}</span>
        </article>
        <article>
          <b>流れ</b>
          <span>{proposal.score.process_aligned ? "整列" : "逆行あり"}</span>
        </article>
        {result.effectiveness ? (
          <article>
            <b>推定ギャップ</b>
            <span>{result.effectiveness.estimated_gap_rate}%</span>
          </article>
        ) : null}
      </div>
      <p>{proposal.process_summary}</p>
      {proposal.reasons.length > 0 ? (
        <ul className="reasons">
          {proposal.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      <p>
        物流 {proposal.score.flow_cost} / 隣接 {proposal.score.adjacency_penalty} / 工程流れ{" "}
        {proposal.score.process_penalty} / 評価 {result.evaluations} / {result.algorithm}
      </p>
      <div className="maps">
        <FactoryGrid title="初期解（貪欲）" grid={result.initial_grid} departments={departments} />
        <FactoryGrid
          title={proposal.label}
          grid={proposal.grid}
          departments={departments}
          path={proposal.path}
        />
      </div>
    </section>
  );
}

function RelationList({ relations }: { relations: Relation[] }) {
  if (relations.length === 0) return null;
  return (
    <ul className="relations">
      {relations.map((r) => (
        <li key={`${r.a}-${r.b}-${r.kind}`}>
          {r.kind === "prefer" ? "隣接希望" : "離隔必須"}: {r.a} — {r.b}
          {r.kind === "forbid" ? `（${r.min_cell_distance}セル以上）` : ""}
        </li>
      ))}
    </ul>
  );
}
