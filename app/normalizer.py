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
    stats = raw.get("stats", {})
    upgrade = stats.get("upgrade", {})

    delta_current = {}
    delta_potential = {}

    for key, val in upgrade.items():
        try:
            i_value = int(val)
        except (TypeError, ValueError):
            continue

        # 잠재력 항목 분리
        if key.endswith(POT_SUFFIX):
            base = key[: -len(POT_SUFFIX)]
            if base in ATTR_MAP:
                stat = ATTR_MAP[base]
                delta_potential[stat] = delta_potential.get(stat, 0) + i_value
        else:
            if key in ATTR_MAP:
                stat = ATTR_MAP[key]
                delta_current[stat] = delta_current.get(stat, 0) + i_value

    stats_damage = extract_float_dict(stats.get("damage", {}))
    stats_equip = extract_float_dict(stats.get("equip", {}))
    stats_use = extract_float_dict(stats.get("use", {}))
    needs_raw = raw.get("needs", "")
    # 범위 데이터들 미리 파싱
    r_min, r_max = parse_range(raw.get("atk_range", "0-0"))
    d_min, d_max = parse_range(raw.get("dmg_range", "0-0"))

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
        desc=raw.get("desc", ""),
        base_dmg=raw.get("base_dmg", 0.0),
        mana_cost=raw.get("mana_cost", 0.0),
        upgrade_total=raw.get("upgrade_total", 0),
        max_use=raw.get("max_use", 0),
        range_min=r_min,
        range_max=r_max,
        dmg_range_min=d_min,
        dmg_range_max=d_max,
        visual_effect=raw.get("visual_effect", []),
        atk_posture=raw.get("atk_posture", [0] * 6),
        def_posture=raw.get("def_posture", [0] * 6),
        weapon=raw.get("weapon", ""),
        dmg_bonus=stats_damage,
        equip_bonus=stats_equip,
        use_effect=stats_use,
    )


def parse_scaling_text(text: str) -> dict[str, float]:
    """
    "力道2,拳掌4,内力0.2" 형태의 문자열을 딕셔너리로 변환합니다.
    """
    result = {}
    if not text or not isinstance(text, str):
        return result

    # 1. 쉼표로 각 항목 분리
    items = text.split(',')

    for item in items:
        item = item.strip()
        if not item:
            continue

        # 2. 정규표현식으로 문자와 숫자(소수점 포함) 분리
        # ([^\d\.]+): 숫자가 아닌 부분 (키 이름)
        # ([\d\.]+): 숫자 또는 소수점 부분 (값)
        match = re.match(r"([^\d\.]+)([\d\.]+)", item)

        if match:
            key = match.group(1).strip()
            try:
                value = float(match.group(2))
                result[key] = value
            except ValueError:
                continue

    return result


def parse_range(range_str: str, default_val: int = 0) -> tuple[int, int]:
    """
    "0-4" 형태의 문자열을 파싱하여 (min, max) 튜플을 반환합니다.
    """
    if not range_str or not isinstance(range_str, str) or '-' not in range_str:
        # 값이 없거나 형식이 맞지 않으면 기본값 처리
        val = int(range_str) if str(range_str).isdigit() else default_val
        return val, val

    try:
        parts = range_str.split('-')
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return default_val, default_val


"""
    dmg_bonus: dict[str, float] = field(default_factory=dict)
    equip_bonus: dict[str, float] = field(default_factory=dict)
    use_effect: dict[str, float] = field(default_factory=dict)


"""
"""
"stats": {
                "damage": {
                    "내력": 0.1,
                    "의지": 2,
                    "장병": 2
                },
                "equip": [],
                "upgrade": {
                    "意志": 1
                },
                "use": {
                    "疲劳": 4
                }
            },
"""


def extract_float_dict(data_source: dict) -> dict[str, float]:
    """
    딕셔너리를 순회하며 float로 변환 가능한 값만 추출하여 새 딕셔너리를 반환합니다.
    """
    result = {}
    if not data_source or not isinstance(data_source, dict):
        return result

    for key, val in data_source.items():
        try:
            # 문자열일 수도 있으니 int로 변환 시도
            result[key] = float(val)
        except (TypeError, ValueError):
            # 숫자가 아니면 무시 (로그를 남기거나 기본값을 줄 수도 있음)
            continue
    return result


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
