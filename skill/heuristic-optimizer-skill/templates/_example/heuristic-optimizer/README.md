# Heuristic Optimizer

Python + FastAPI + React / Next.js / TypeScript による、TSP（巡回セールスマン問題）の簡易ヒューリスティック解探索サンプルです。

## アルゴリズム
1. 地点群を入力
2. 最近傍貪欲法で初期実行可能解を生成
3. 2-optで近傍解を生成
4. 総巡回距離を目的関数として評価
5. 改善がなくなるまで局所探索

厳密最適解を保証する実装ではなく、ヒューリスティックによる近似解探索です。

## 構成
- `backend/`: FastAPI / Python
- `frontend/`: Next.js / React / TypeScript
- API: `POST /optimize`, `GET /health`

## Backend 起動
```bash
cd backend
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API docs: `http://localhost:8000/docs`

## Frontend 起動
```bash
cd frontend
npm install
# 必要なら .env.local.example を .env.local にコピー
npm run dev
```
ブラウザ: `http://localhost:3000`

## API例
`POST /optimize`
```json
{"points":[{"name":"A","x":0,"y":0},{"name":"B","x":2,"y":6},{"name":"C","x":5,"y":3}]}
```

## 定式化
目的関数は巡回経路の総距離 `min Σ d(x_i, x_{i+1})`。全地点を1回ずつ訪問し、最後に開始地点へ戻る経路を扱います。
