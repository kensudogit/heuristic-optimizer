# 工場建設レイアウト最適化 PoC

建設時の工場レイアウト（施設配置）を、ヒューリスティックで探索する PoC です。
Python 3.12 + FastAPI と Next.js / React / TypeScript で動きます。

ヒューリスティックでは条件を満たす複数案を返します。厳密モードを選ぶと、分枝限定が探索し切れたときだけ証明済みの「最適解」を返します。

顧客向けの検証結果は [`docs/顧客向け検証報告.md`](docs/顧客向け検証報告.md) にまとめています。

## 定式化

- 入力: 敷地グリッド、工程の寸法と役割（入庫 / 製造 / 出庫 / 付帯）、物流量、隣接希望、離隔、禁止セル、工程チェーン
- 決定変数: 各工程の左上セル `(row, col)` と向き
- 目的関数（最小化）:
  - 物流費用 \(\sum_{ij} f_{ij}\, d(c_i, c_j)\)（重心間マンハッタン距離）
  - 隣接希望の未達ペナルティ
  - 入庫→製造→出庫が北から南へ進まないときの逆行ペナルティ
- ハード制約: 敷地内、非重複、禁止セル、固定工程、離隔
- 実行可能解: 上記を満たす全工程の配置
- 厳密解は不要。PoC として近似解でよい

## アルゴリズム

1. 物流量の大きい工程から置く。工程チェーンは北→南の帯へ誘導する（貪欲法）
2. 提案数の3倍まで複数スタートし、配置の違う案を残す
3. 逆行修正・2棟交換・再配置/回転 + Simulated Annealing で改善する
4. 整列を優先して並べ、物流下界との推定ギャップを返す
5. 「厳密最適」を選ぶと分枝限定が同じ目的関数の最適解を証明する。時間切れなら未証明の最良解を返す

選定理由: 施設配置は組み合わせの割当問題であり、貪欲 + 局所探索 / SA が規模と説明可能性のバランスがよい。
下界は2棟だけの最短物流の合計で、他棟との競合は無視する。厳密ギャップではない。

## 起動（Docker）

8000 / 3000 は他システムで使われやすいので、既定は API 8010・画面 3010 です。
画面からの API 呼び出しはコンテナ内で `/api` 経由になるため、ブラウザは 3010 だけ見れば動きます。

```bash
# Windows の Docker Desktop では bake を切る
set COMPOSE_BAKE=false
docker compose up --build
```

- アプリ: http://localhost:3010
- API: http://localhost:8010/docs

バックグラウンド起動は `docker compose up --build -d`、停止は `docker compose down` です。
ポートを変えるときは `BACKEND_PORT` / `FRONTEND_PORT` を付けます。

コマンドプロンプトなら `start.cmd`、PowerShell なら `.\start.ps1`、Linux / Railway なら `./start.sh` です。

## Railway

リポジトリ直下は backend と frontend が並んでいるため、Railpack は言語を判定できません。
ルートの `railway.toml` と `Dockerfile` で、API と画面を1サービスにまとめています。

1. GitHub リポジトリから Deploy する
2. ビルダは Dockerfile（`railway.toml` で指定済み）
3. 公開 URL が画面。API は同じオリジンの `/api`

2サービスに分ける場合は、backend / frontend それぞれで Root Directory を設定します。
frontend の `API_INTERNAL_URL` には backend の内部 URL を入れてください。

## 起動（ローカル）

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

- アプリ: http://localhost:3000
- API: http://localhost:8000/docs

3000 / 8000 が使用中なら、フロントを `--port 3010`、API を `--port 8010` にし、
`FRONTEND_ORIGINS` と `NEXT_PUBLIC_API_URL` を合わせてください。

## API

- `GET /health`
- `GET /sample` — PoC 用の組立工場サンプル
- `POST /optimize` — 初期解と複数案、グリッド、費用内訳、提案理由、工程パス、評価回数を返す。1×1 かつ敷地が小さいときだけ `exact_best` と `optimality_gap` を埋める

不正入力・実行可能解なし・API 切断は 400 / 422 / 画面エラーで返します。

## テスト

```bash
cd backend
.venv\Scripts\python.exe -m pytest -q
```

2×2・3工程は全列挙の最短費用と一致することを確認します。サンプル7工程は実行可能で、危険物庫と事務所の離隔を保ちます。

## 制約事項

- 最適性は保証しない
- 探索は `services/optimizer.py` に閉じ、ルートへ埋め込まない
- 乱数を使う場合は `seed` で再現する
- 大規模入力は `max_passes` または `time_limit_ms` で打ち切る
- 通路形状や建屋の凹凸、階数、ユーティリティ容量は未対応
