# app/plan_store.py
# 최적화 결과(플랜)를 저장/로드하는 모듈

import json
from pathlib import Path

PLAN_DIR = Path("plans")


def save_plan(name: str, data: dict):
    PLAN_DIR.mkdir(exist_ok=True)

    path = PLAN_DIR / f"{name}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_plan(name: str) -> dict:
    path = PLAN_DIR / f"{name}.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_plans():
    PLAN_DIR.mkdir(exist_ok=True)
    return [p.stem for p in PLAN_DIR.glob("*.json")]


def delete_plan(name: str):
    path = PLAN_DIR / f"{name}.json"
    if path.exists():
        path.unlink()