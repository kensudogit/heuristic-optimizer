---
name: heuristic-optimizer-skill
description: >
  最適化問題を定式化し、ヒューリスティックアルゴリズムによる解探索を Python + FastAPI + React/Next.js/TypeScript で繰り返し実装するときに使う。
  「最適化問題を実装して」「ヒューリスティック探索を作って」「TSP・配送・スケジューリング・割当問題をWebアプリ化して」
  「FastAPIとNext.jsで最適化API/UIを作って」「貪欲法、2-opt、局所探索、焼きなまし、遺伝的アルゴリズムを実装して」等の依頼で参照する。
---

# Heuristic Optimizer Skill

## 目的
現実の最適化課題を、再現可能な手順で「定式化 → 解法選定 → Python実装 → FastAPI化 → Next.js UI化 → テスト → README/ZIP成果物」に落とし込む。

## 標準技術スタック
- Backend: Python 3.12+, FastAPI, Pydantic, Uvicorn
- Frontend: Next.js, React, TypeScript
- API: JSON REST
- Test: pytest（Backend）、必要に応じて Vitest/React Testing Library（Frontend）

## 実行手順
1. 問題を整理する。
   - 入力データ
   - 意思決定変数
   - 目的関数（最小化/最大化）
   - 制約条件
   - 実行可能解の定義
   - 計算時間・解品質などの非機能条件
2. 数理モデルを文章と数式で明示する。厳密解が必要か、近似解でよいかを区別する。
3. 問題規模と制約に応じて探索法を選ぶ。
   - 初期解: 貪欲法、ランダム生成等
   - 改善: 2-opt、局所探索、山登り法、Simulated Annealing、Tabu Search、Genetic Algorithm 等
4. 探索ロジックをUI/APIから分離した純粋なPythonモジュールとして実装する。
5. 評価関数、制約違反判定、近傍生成、終了条件を明示する。
6. FastAPIでリクエスト/レスポンスモデルを定義し、最適化エンドポイントを公開する。
7. Next.js + TypeScriptで入力、実行、結果、初期解との比較、改善率を表示する。
8. 異常系を実装する。不正入力、空データ、実行可能解なし、API失敗を処理する。
9. 小規模データでは全探索または既知解と比較し、ヒューリスティック解の妥当性を検証する。
10. READMEに定式化、アルゴリズム、ディレクトリ構成、起動方法、API仕様、制約事項を記載する。
11. 成果物要求がある場合は不要なキャッシュや依存物を除外してZIP化する。

## 標準ディレクトリ
```text
project/
  backend/
    app/
      main.py
      models.py
      services/
        optimizer.py
    tests/
    requirements.txt
  frontend/
    app/
    components/
    lib/
    package.json
    tsconfig.json
    .env.local.example
  README.md
```

## 実装原則
- 目的関数と制約条件をコード上でも識別可能にする。
- 探索アルゴリズムをFastAPIルートへ直接埋め込まない。
- 初期解、最終解、目的関数値、改善量、改善率、探索回数を可能な範囲で返す。
- 乱数を使う場合はseed指定を可能にして再現性を確保する。
- 大規模入力には最大反復回数または時間上限を設定する。
- 「最適解」と「ヒューリスティックにより得られた最良解」を混同しない。
- CORS、環境変数、入力バリデーションを設定する。
- TypeScriptで `any` の濫用を避け、API型を定義する。

## TSP標準例
目的関数は巡回距離の最小化とする。初期解をNearest Neighborで作成し、2-optで局所改善する。開始地点を固定する場合は探索中も固定する。

## 完了条件
- Backendが起動できる。
- Frontendが起動できる。
- UIからAPIを呼び出せる。
- サンプルデータで改善前後を確認できる。
- READMEだけで第三者が起動できる。
- nameとSkill親フォルダ名が一致している。
