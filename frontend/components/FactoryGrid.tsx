import type { Department, PathPoint } from "@/lib/types";

const PALETTE = [
  "#2563eb",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#db2777",
  "#0f766e",
  "#b45309",
  "#4338ca",
];

type Props = {
  title: string;
  grid: string[][];
  departments: Department[];
  path?: PathPoint[];
};

export function FactoryGrid({ title, grid, departments, path = [] }: Props) {
  const colorOf = new Map(departments.map((d, i) => [d.id, PALETTE[i % PALETTE.length]]));
  const nameOf = new Map(departments.map((d) => [d.id, d.name]));
  const rows = grid.length;
  const cols = grid[0]?.length ?? 1;
  return (
    <figure className="factory">
      <figcaption>{title}</figcaption>
      <div className="factory-wrap">
        <div
          className="grid"
          style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
          role="img"
          aria-label={title}
        >
          {grid.flatMap((row, r) =>
            row.map((cell, c) => {
              const blocked = cell === "blocked";
              const empty = cell === "";
              const bg = blocked ? "#94a3b8" : empty ? "#f8fafc" : colorOf.get(cell) ?? "#334155";
              return (
                <div
                  key={`${r}-${c}`}
                  className="cell"
                  style={{ background: bg, color: blocked || empty ? "#334155" : "#fff" }}
                  title={blocked ? "通路・ユーティリティ" : empty ? "空き" : nameOf.get(cell) ?? cell}
                >
                  {blocked ? "×" : empty ? "" : cell}
                </div>
              );
            }),
          )}
        </div>
        {path.length >= 2 ? (
          <svg
            className="process-path"
            viewBox={`0 0 ${cols} ${rows}`}
            preserveAspectRatio="none"
            aria-hidden
          >
            <polyline
              fill="none"
              stroke="#0f172a"
              strokeWidth="0.12"
              strokeLinejoin="round"
              strokeLinecap="round"
              points={path.map((p) => `${p.col + 0.5},${p.row + 0.5}`).join(" ")}
            />
            {path.map((p, i) => (
              <circle
                key={`${p.row}-${p.col}-${i}`}
                cx={p.col + 0.5}
                cy={p.row + 0.5}
                r="0.18"
                fill={i === 0 ? "#16a34a" : i === path.length - 1 ? "#dc2626" : "#f8fafc"}
                stroke="#0f172a"
                strokeWidth="0.06"
              />
            ))}
          </svg>
        ) : null}
      </div>
    </figure>
  );
}
