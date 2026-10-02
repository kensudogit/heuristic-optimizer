import type { ApiErrorBody, OptimizeRequest, OptimizeResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function formatDetail(body: ApiErrorBody | string): string {
  if (typeof body === "string") return body;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((item) => item.msg ?? JSON.stringify(item)).join(" / ");
  }
  return "最適化に失敗しました";
}

async function parseError(res: Response): Promise<string> {
  try {
    return formatDetail((await res.json()) as ApiErrorBody);
  } catch {
    return (await res.text()) || `APIエラー (${res.status})`;
  }
}

export async function fetchSample(): Promise<OptimizeRequest> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/sample`);
  } catch {
    throw new Error("APIに接続できません。バックエンドが起動しているか確認してください");
  }
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as OptimizeRequest;
}

export async function optimize(req: OptimizeRequest): Promise<OptimizeResponse> {
  if (req.departments.length < 1) throw new Error("工程が空です");
  const ids = req.departments.map((d) => d.id.trim());
  if (ids.some((id) => !id)) throw new Error("工程IDが空です");
  if (new Set(ids).size !== ids.length) throw new Error("工程IDは重複できません");

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/optimize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
  } catch {
    throw new Error("APIに接続できません。バックエンドが起動しているか確認してください");
  }
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as OptimizeResponse;
}
