from dataclasses import dataclass
from math import hypot
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Heuristic Route Optimizer", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class PointIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    x: float
    y: float

class OptimizeRequest(BaseModel):
    points: List[PointIn] = Field(min_length=3)

class OptimizeResponse(BaseModel):
    initial_route: List[str]
    optimized_route: List[str]
    initial_distance: float
    optimized_distance: float
    improvement: float
    improvement_rate: float

@dataclass(frozen=True)
class Point:
    name: str
    x: float
    y: float

def distance(a: Point, b: Point) -> float:
    return hypot(a.x - b.x, a.y - b.y)

def route_distance(route: List[Point]) -> float:
    return sum(distance(route[i], route[(i + 1) % len(route)]) for i in range(len(route)))

def greedy(points: List[Point]) -> List[Point]:
    route = [points[0]]
    remaining = points[1:].copy()
    while remaining:
        nxt = min(remaining, key=lambda p: distance(route[-1], p))
        route.append(nxt)
        remaining.remove(nxt)
    return route

def two_opt(route: List[Point]) -> List[Point]:
    best = route.copy()
    best_distance = route_distance(best)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                candidate_distance = route_distance(candidate)
                if candidate_distance + 1e-12 < best_distance:
                    best, best_distance, improved = candidate, candidate_distance, True
    return best

def names(route: List[Point]) -> List[str]:
    return [p.name for p in route] + [route[0].name]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/optimize", response_model=OptimizeResponse)
def optimize(req: OptimizeRequest):
    if len({p.name for p in req.points}) != len(req.points):
        raise HTTPException(400, "Point names must be unique")
    points = [Point(p.name, p.x, p.y) for p in req.points]
    initial = greedy(points)
    optimized = two_opt(initial)
    d0, d1 = route_distance(initial), route_distance(optimized)
    improvement = d0 - d1
    return OptimizeResponse(initial_route=names(initial), optimized_route=names(optimized), initial_distance=round(d0, 4), optimized_distance=round(d1, 4), improvement=round(improvement, 4), improvement_rate=round((improvement / d0 * 100) if d0 else 0, 2))
