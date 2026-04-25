# run.py

from app.loaders import load_json
from app.translator import load_kr_dict, translate
from app.normalizer import normalize_skill
from app.grouper import group_skills
from app.optimizer import (
    StatBlock,
    GoalConfig,
    RarityConstraint,
    optimize_groups,
    STAT_ORDER,
)

JSON_PATH = "data/martial_skills.json"
DICT_PATH = "data/kr_dict.lua"


def make_default_state():
    current = {k: 10 for k in STAT_ORDER}
    potential = {k: 60 for k in STAT_ORDER}
    return StatBlock(current=current, potential=potential)


def make_small_goal():
    enabled = {k: False for k in STAT_ORDER}

    enabled["근력"] = True
    enabled["검"] = True

    target_current = {k: 0 for k in STAT_ORDER}
    target_potential = {k: 0 for k in STAT_ORDER}

    target_current["근력"] = 20
    target_potential["근력"] = 65
    target_current["검"] = 20
    target_potential["검"] = 65

    return GoalConfig(
        enabled=enabled,
        target_current=target_current,
        target_potential=target_potential,
    )


def main():
    data = load_json(JSON_PATH)
    kr = load_kr_dict(DICT_PATH)

    skills = []
    for raw in data["skills"]:
        s = normalize_skill(raw)
        s.name = translate(s.name, kr)
        s.rare = translate(s.rare, kr)
        skills.append(s)

    groups = group_skills(skills)

    print("총 비급:", len(skills))
    print("그룹 수:", len(groups))

    pot_count = 0
    pot_examples = []

    for s in skills:
        if s.delta_potential:
            pot_count += 1
            if len(pot_examples) < 10:
                pot_examples.append((s.name, s.delta_current, s.delta_potential, s.rare))

    print("잠재력 증가 비급 수:", pot_count)
    print("\n=== 잠재력 있는 샘플 10개 ===")
    for name, cur, pot, rare in pot_examples:
        print(f"[{rare}] {name} | 현재: {cur} | 잠재: {pot}")

    print("\n=== 샘플 그룹 5개 ===")
    for g in groups[:5]:
        print("------")
        print("개수:", g.count)
        print("현재:", g.delta_current)
        print("잠재:", g.delta_potential)
        print("예시:", g.skills[0].name)

    initial_state = make_default_state()
    goal = make_small_goal()

    rarity_constraint = RarityConstraint(
        enabled={},
        max_books={}
    )

    for g in groups:
        rare = g.skills[0].rare
        rarity_constraint.enabled.setdefault(rare, True)
        rarity_constraint.max_books.setdefault(rare, 999)

    result = optimize_groups(
        initial_state=initial_state,
        goal=goal,
        rarity_constraint=rarity_constraint,
        groups=groups,
        time_limit_seconds=10,
        max_retry_cuts=10,
    )

    print("\n=== 최적화 결과 ===")
    print("성공:", result.success)
    print("메시지:", result.message)
    print("사용 비급 수:", result.used_books_total)
    print("총 단계 수:", result.used_levels_total)
    print("초과 점수:", result.overshoot_score)

    if result.success:
        print("\n=== 선택 그룹 ===")
        for idx, choice in enumerate(result.choices, start=1):
            g = groups[choice.group_index]
            example_name = g.skills[0].name
            rare = g.skills[0].rare
            print(
                f"{idx}. [{rare}] {example_name} | "
                f"권수 {choice.books_used} | 총 단계 {choice.levels_used} | "
                f"그룹개수 {g.count} | 현재 {g.delta_current} | 잠재 {g.delta_potential}"
            )

        print("\n=== 최종 상태 ===")
        for stat in STAT_ORDER:
            print(
                f"{stat}: "
                f"{result.final_state.current.get(stat, 0)} / "
                f"{result.final_state.potential.get(stat, 0)}"
            )


if __name__ == "__main__":
    main()