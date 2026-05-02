# app/loaders.py
import json
import sqlite3

from app.models import Skill


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_skills_from_db(db_path) -> list[Skill]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, name, rare, rare_lv, force_name, type_name, needs,"
        "       need_current, delta_current, delta_potential"
        " FROM skills ORDER BY id"
    ).fetchall()
    conn.close()

    skills = []
    for row in rows:
        (id_, name, rare, rare_lv, force_name, type_name, needs,
         need_current_json, delta_current_json, delta_potential_json) = row
        skills.append(Skill(
            id=id_,
            name=name,
            rare=rare,
            rare_lv=rare_lv,
            force_name=force_name,
            type_name=type_name,
            needs=needs,
            need_current=json.loads(need_current_json),
            delta_current=json.loads(delta_current_json),
            delta_potential=json.loads(delta_potential_json),
        ))
    return skills


__all__ = ["load_json", "load_skills_from_db"]
