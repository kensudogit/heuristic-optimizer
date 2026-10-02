# 工場建設レイアウト最適化 PoC

建設時の工場レイアウト（施設配置）を、ヒューリスティックで探索する PoC です。
Python 3.12 + FastAPI と Next.js / React / TypeScript で動きます。

返る配置は **条件を満たす複数のヒューリスティック案** です。厳密な最適解は保証しません。

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

1. 物流量の大きい工程から、増分費用の小さい位置へ置く（貪欲法）
2. 複数スタートで上位候補から選んで、異なる実行可能パターンを生成する
3. 再配置・回転の局所探索 + Simulated Annealing で改善する
4. 重複を除き、費用の小さい順に複数案として返す

選定理由: 施設配置は組み合わせの割当問題であり、貪欲 + 局所探索 / SA が規模と説明可能性のバランスがよい。

## 起動

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
"# heuristic-optimizer" 
