from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_sample_and_optimize() -> None:
    sample = client.get("/sample")
    assert sample.status_code == 200
    body = sample.json()
    assert len(body["departments"]) == 7
    res = client.post("/optimize", json=body)
    assert res.status_code == 200
    out = res.json()
    assert out["best_score"]["feasible"] is True
    assert out["best_score"]["total"] <= out["initial_score"]["total"] + 1e-9
    assert "ヒューリスティック" in out["note"]
    assert len(out["best_grid"]) == body["rows"]
    assert len(out["best_grid"][0]) == body["cols"]
    assert len(out["proposals"]) >= 1
    assert out["proposals"][0]["label"] == "案1"
    assert out["proposals"][0]["reasons"]
    assert len(out["proposals"][0]["path"]) == 5
    assert out["exact_best"] is None
    assert out["optimality_gap"] is None


def test_tiny_optimize_returns_exact_gap() -> None:
    res = client.post(
        "/optimize",
        json={
            "rows": 2,
            "cols": 2,
            "departments": [
                {"id": "A", "name": "受入", "width": 1, "height": 1, "rotatable": False},
                {"id": "B", "name": "加工", "width": 1, "height": 1, "rotatable": False},
                {"id": "C", "name": "出荷", "width": 1, "height": 1, "rotatable": False},
            ],
            "flows": [
                {"from_id": "A", "to_id": "B", "volume": 10},
                {"from_id": "B", "to_id": "C", "volume": 1},
            ],
            "seed": 1,
            "max_passes": 20,
            "n_proposals": 2,
        },
    )
    assert res.status_code == 200
    out = res.json()
    assert out["exact_best"] is not None
    assert out["optimality_gap"] == 0
    assert "ギャップ" in out["note"]


def test_optimize_rejects_empty() -> None:
    res = client.post(
        "/optimize",
        json={"rows": 4, "cols": 4, "departments": []},
    )
    assert res.status_code == 422


def test_optimize_rejects_overlap_impossible() -> None:
    res = client.post(
        "/optimize",
        json={
            "rows": 2,
            "cols": 2,
            "departments": [
                {"id": "A", "name": "A", "width": 2, "height": 2},
                {"id": "B", "name": "B", "width": 2, "height": 2},
            ],
        },
    )
    assert res.status_code == 400
    assert "実行可能解なし" in res.json()["detail"]
