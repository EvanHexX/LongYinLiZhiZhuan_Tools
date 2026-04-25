# app/normalizer.py
# JSON 원본 비급 데이터를 내부 Skill 모델로 변환합니다.

import re
from app.constants import ATTR_MAP
from app.models import Skill

POT_SUFFIX = "潜力"


def normalize_skill(raw):
    """
    raw JSON skill 데이터를 내부 Skill 객체로 변환합니다.
    """
    upgrade = raw.get("stats", {}).get("upgrade", {})

    delta_current = {}
    delta_potential = {}

    for key, val in upgrade.items():
        try:
            i_value = int(val)
        except (TypeError, ValueError):
            continue

        # ✅ 잠재력 항목 분리
        if key.endswith(POT_SUFFIX):
            base = key[: -len(POT_SUFFIX)]
            if base in ATTR_MAP:
                stat = ATTR_MAP[base]
                delta_potential[stat] = delta_potential.get(stat, 0) + i_value
        else:
            if key in ATTR_MAP:
                stat = ATTR_MAP[key]
                delta_current[stat] = delta_current.get(stat, 0) + i_value

    needs_raw = raw.get("needs", "")

    return Skill(
        id=int(raw["id"]),
        name=raw.get("name", ""),
        rare=raw.get("rare_name", ""),
        rare_lv=int(raw.get("rare_lv", 0)),
        force_name=raw.get("force_name", "江湖"),
        type_name=raw.get("type_name", "기타"),
        needs=needs_raw,
        need_current=parse_needs(needs_raw),
        delta_current=delta_current,
        delta_potential=delta_potential,
    )


def parse_needs(needs_raw: str) -> dict:
    """
    예:
    力道20/内功30
    → {"근력":20, "내공":30}
    """
    if not needs_raw:
        return {}

    result = {}

    parts = re.split(r"[\/, ]+", needs_raw)

    for p in parts:
        m = re.match(r"(.+?)(\d+)", p)
        if not m:
            continue

        stat_zh = m.group(1)
        value = int(m.group(2))

        stat_ko = ATTR_MAP.get(stat_zh)
        if stat_ko:
            result[stat_ko] = value

    return result
