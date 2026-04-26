# app/greedy_optimizer.py
# 단계형 A/B/C 기반 greedy 최적화 엔진입니다.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from app.optimizer import (
    STAT_ORDER,
    StatBlock,
    GoalConfig,
    RarityConstraint,
    clone_state,
    apply_group_levels,
)
from app.snapshot import BookAction, check_needs
from app.constants import C_GAP_THRESHOLD, LEVEL_CANDIDATES, LOW_CURRENT_RARITIES, LOW_POTENTIAL_RARITIES_1, \
    LOW_POTENTIAL_RARITIES_2, MAIN_POTENTIAL_RARITIES, RARITY_RANK, RARITY_MIN_ACTIVE_STAT, \
    RARITY_MAX_EXPERIENCE_QUANTITY


@dataclass
class GreedyOptimizationResult:
    success: bool
    actions: List[BookAction]
    final_state: StatBlock
    used_books_total: int
    used_levels_total: int
    overshoot_score: int
    message: str = ""


def _enabled_stats(goal: GoalConfig) -> list[str]:
    return [s for s in STAT_ORDER if goal.enabled.get(s, True)]


def _abc(state: StatBlock, goal: GoalConfig) -> dict:
    return {
        stat: {
            "A": max(0, goal.target_current.get(stat, 0) - state.current.get(stat, 0)),
            "B": max(0, goal.target_potential.get(stat, 0) - state.potential.get(stat, 0)),
            "C": max(0, state.potential.get(stat, 0) - state.current.get(stat, 0)),
        }
        for stat in _enabled_stats(goal)
    }


def _goal_reached(state: StatBlock, goal: GoalConfig) -> bool:
    for stat in _enabled_stats(goal):
        if state.current.get(stat, 0) < goal.target_current.get(stat, 0):
            return False
        if state.potential.get(stat, 0) < goal.target_potential.get(stat, 0):
            return False
    return True


def _deficit_score(state: StatBlock, goal: GoalConfig) -> int:
    total = 0
    for stat in _enabled_stats(goal):
        total += max(0, goal.target_current.get(stat, 0) - state.current.get(stat, 0))
        total += max(0, goal.target_potential.get(stat, 0) - state.potential.get(stat, 0))
    return total


def _overshoot_score(state: StatBlock, goal: GoalConfig) -> int:
    total = 0
    for stat in _enabled_stats(goal):
        total += max(0, state.current.get(stat, 0) - goal.target_current.get(stat, 0))
        total += max(0, state.potential.get(stat, 0) - goal.target_potential.get(stat, 0))
    return total


def _state_valid(state: StatBlock) -> bool:
    return all(state.current.get(stat, 0) <= state.potential.get(stat, 0) for stat in STAT_ORDER)


def _rarity_allowed_by_min_stat(state: StatBlock, goal: GoalConfig, rare: str) -> bool:
    min_value = RARITY_MIN_ACTIVE_STAT.get(rare, 0)
    if min_value <= 0:
        return True

    enabled = _enabled_stats(goal)
    if not enabled:
        return True

    # 목표로 삼은 스탯 중 하나라도 최소 고려치에 도달하면 해당 등급을 후보로 본다.
    return max(state.current.get(stat, 0) for stat in enabled) >= min_value


def _rarity_hard_allowed(skill, rarity_constraint: RarityConstraint, used_books_by_rare: Dict[str, int]) -> bool:
    rare = skill.rare
    if not rarity_constraint.enabled.get(rare, True):
        return False

    hard_max = rarity_constraint.max_books.get(rare, 999999)
    return used_books_by_rare[rare] < hard_max


def _experience_penalty(rare: str, used_books_by_rare: Dict[str, int]) -> int:
    base = RARITY_MAX_EXPERIENCE_QUANTITY.get(rare, 999999)
    used_after = used_books_by_rare[rare] + 1

    if used_after <= base:
        return 0

    # 기준권수 초과분은 강하게 벌점.
    return (used_after - base) * 5000


def _level_candidates(state: StatBlock, group, goal: GoalConfig, focus_stat: Optional[str] = None) -> list[int]:
    candidates = set(LEVEL_CANDIDATES)

    stats = [focus_stat] if focus_stat else _enabled_stats(goal)

    for stat in stats:
        if not stat:
            continue

        dc = group.delta_current.get(stat, 0)
        dp = group.delta_potential.get(stat, 0)

        a = max(0, goal.target_current.get(stat, 0) - state.current.get(stat, 0))
        b = max(0, goal.target_potential.get(stat, 0) - state.potential.get(stat, 0))
        c = max(0, state.potential.get(stat, 0) - state.current.get(stat, 0))

        if dc > 0 and a > 0:
            candidates.add(max(1, min(10, (a + dc - 1) // dc)))

        if dp > 0 and b > 0:
            candidates.add(max(1, min(10, (b + dp - 1) // dp)))

        if dc > 0 and c > C_GAP_THRESHOLD:
            need = c - C_GAP_THRESHOLD
            candidates.add(max(1, min(10, (need + dc - 1) // dc)))

    return sorted(c for c in candidates if 1 <= c <= 10)


def _progress(before: StatBlock, after: StatBlock, goal: GoalConfig) -> dict:
    result = {
        "A_reduced": 0,
        "B_reduced": 0,
        "C_reduced": 0,
        "waste": 0,
        "combo_A": 0,
        "combo_B": 0,
    }

    before_abc = _abc(before, goal)
    after_abc = _abc(after, goal)

    for stat in _enabled_stats(goal):
        a_red = before_abc[stat]["A"] - after_abc[stat]["A"]
        b_red = before_abc[stat]["B"] - after_abc[stat]["B"]
        c_red = before_abc[stat]["C"] - after_abc[stat]["C"]

        if a_red > 0:
            result["A_reduced"] += a_red
            result["combo_A"] += 1

        if b_red > 0:
            result["B_reduced"] += b_red
            result["combo_B"] += 1

        if before_abc[stat]["C"] > C_GAP_THRESHOLD and c_red > 0:
            result["C_reduced"] += c_red

    for stat in STAT_ORDER:
        cur_gain = max(0, after.current.get(stat, 0) - before.current.get(stat, 0))
        pot_gain = max(0, after.potential.get(stat, 0) - before.potential.get(stat, 0))

        if not goal.enabled.get(stat, True):
            result["waste"] += cur_gain + pot_gain
            continue

        if before.current.get(stat, 0) >= goal.target_current.get(stat, 0):
            result["waste"] += cur_gain

        if before.potential.get(stat, 0) >= goal.target_potential.get(stat, 0):
            result["waste"] += pot_gain

    return result


def _apply_candidate(state: StatBlock, group, levels: int) -> Optional[StatBlock]:
    after = apply_group_levels(
        state=state,
        delta_current=group.delta_current,
        delta_potential=group.delta_potential,
        levels=levels,
    )
    if not _state_valid(after):
        return None
    return after


def _make_action(group_index: int, skill_index: int, levels: int) -> BookAction:
    return BookAction(
        group_index=group_index,
        book_no_in_group=1,
        levels_used=levels,
        default_skill_index=skill_index,
        selected_skill_index=skill_index,
    )


def _make_result(success: bool, actions: List[BookAction], state: StatBlock, goal: GoalConfig, message: str):
    return GreedyOptimizationResult(
        success=success,
        actions=actions,
        final_state=state,
        used_books_total=len(actions),
        used_levels_total=sum(a.levels_used for a in actions),
        overshoot_score=_overshoot_score(state, goal),
        message=message,
    )


def _iter_usable_skills(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
):
    for group_index, group in enumerate(groups):
        for skill_index, skill in enumerate(group.skills):
            if skill.id in used_skill_ids:
                continue

            if not _rarity_hard_allowed(skill, rarity_constraint, used_books_by_rare):
                continue

            if not _rarity_allowed_by_min_stat(state, goal, skill.rare):
                continue

            if not check_needs(state, skill):
                continue

            yield group_index, group, skill_index, skill


def _select_reduce_c_gap(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
):
    abc = _abc(state, goal)
    c_targets = [(stat, v["C"]) for stat, v in abc.items() if v["C"] > C_GAP_THRESHOLD]

    if not c_targets:
        return None

    c_targets.sort(key=lambda x: x[1], reverse=True)
    focus_stat, _gap = c_targets[0]

    candidates = []

    for group_index, group, skill_index, skill in _iter_usable_skills(
            state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
    ):
        if skill.rare not in LOW_CURRENT_RARITIES:
            continue

        if group.delta_current.get(focus_stat, 0) <= 0:
            continue

        for levels in _level_candidates(state, group, goal, focus_stat=focus_stat):
            after = _apply_candidate(state, group, levels)
            if after is None:
                continue

            p = _progress(state, after, goal)

            if p["C_reduced"] <= 0:
                continue

            rare_rank = RARITY_RANK.get(skill.rare, 99)
            penalty = _experience_penalty(skill.rare, used_books_by_rare)

            score = (
                p["C_reduced"] * 10000,
                p["A_reduced"] * 2000,
                -rare_rank * 1000,
                -penalty,
                -p["waste"] * 500,
                -levels,
            )
            candidates.append((score, group_index, skill_index, skill, levels, after))

    return max(candidates, key=lambda x: x[0]) if candidates else None


def _select_low_rarity_potential(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
        allowed_rarities: set[str],
):
    candidates = []

    for group_index, group, skill_index, skill in _iter_usable_skills(
            state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
    ):
        if skill.rare not in allowed_rarities:
            continue

        # 목표 잠재력 B가 남아있는 스탯의 잠재력을 올리는 비급만.
        useful_stats = []
        for stat in _enabled_stats(goal):
            if group.delta_potential.get(stat, 0) > 0:
                b = max(0, goal.target_potential.get(stat, 0) - state.potential.get(stat, 0))
                if b > 0:
                    useful_stats.append(stat)

        if not useful_stats:
            continue

        for levels in _level_candidates(state, group, goal):
            after = _apply_candidate(state, group, levels)
            if after is None:
                continue

            p = _progress(state, after, goal)
            if p["B_reduced"] <= 0:
                continue

            rare_rank = RARITY_RANK.get(skill.rare, 99)
            penalty = _experience_penalty(skill.rare, used_books_by_rare)

            score = (
                p["B_reduced"] * 10000,
                p["combo_B"] * 2500,
                p["A_reduced"] * 1000,
                -rare_rank * 700,
                -penalty,
                -p["waste"] * 500,
                -levels,
            )
            candidates.append((score, group_index, skill_index, skill, levels, after))

    return max(candidates, key=lambda x: x[0]) if candidates else None


def _select_main_potential(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
):
    abc = _abc(state, goal)
    b_targets = [(stat, v["B"]) for stat, v in abc.items() if v["B"] > 0]

    if not b_targets:
        return None

    b_targets.sort(key=lambda x: x[1], reverse=True)
    b1 = b_targets[0][0]
    b2 = b_targets[1][0] if len(b_targets) > 1 else None
    b3 = b_targets[2][0] if len(b_targets) > 2 else None

    other_goals_done = all(stat == b1 or abc[stat]["A"] == 0 and abc[stat]["B"] == 0 for stat in abc)

    candidates = []

    for group_index, group, skill_index, skill in _iter_usable_skills(
            state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
    ):
        if skill.rare not in MAIN_POTENTIAL_RARITIES:
            continue

        if group.delta_potential.get(b1, 0) <= 0:
            continue

        for levels in _level_candidates(state, group, goal, focus_stat=b1):
            after = _apply_candidate(state, group, levels)
            if after is None:
                continue

            p = _progress(state, after, goal)
            if p["B_reduced"] <= 0:
                continue

            b1_gain = min(
                group.delta_potential.get(b1, 0) * levels,
                max(0, goal.target_potential.get(b1, 0) - state.potential.get(b1, 0)),
            )

            b2_gain = 0
            b3_gain = 0
            if b2:
                b2_gain = min(
                    group.delta_potential.get(b2, 0) * levels,
                    max(0, goal.target_potential.get(b2, 0) - state.potential.get(b2, 0)),
                )
            if b3:
                b3_gain = min(
                    group.delta_potential.get(b3, 0) * levels,
                    max(0, goal.target_potential.get(b3, 0) - state.potential.get(b3, 0)),
                )

            a_support = 0
            for stat in _enabled_stats(goal):
                if abc[stat]["A"] > 0 and group.delta_current.get(stat, 0) > 0:
                    a_support += group.delta_current.get(stat, 0) * levels

            rare_rank = RARITY_RANK.get(skill.rare, 99)
            penalty = _experience_penalty(skill.rare, used_books_by_rare)

            if other_goals_done:
                score = (
                    b1_gain * 20000,
                    a_support * 2000,
                    -rare_rank * 500,
                    -penalty,
                    -p["waste"] * 700,
                    -levels,
                )
            else:
                score = (
                    b1_gain * 15000,
                    b2_gain * 9000,
                    b3_gain * 6000,
                    a_support * 3000,
                    p["combo_B"] * 2000,
                    -rare_rank * 500,
                    -penalty,
                    -p["waste"] * 800,
                    -levels,
                )

            candidates.append((score, group_index, skill_index, skill, levels, after))

    return max(candidates, key=lambda x: x[0]) if candidates else None


def _select_current_progress(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
):
    abc = _abc(state, goal)
    a_targets = [(stat, v["A"]) for stat, v in abc.items() if v["A"] > 0]

    if not a_targets:
        return None

    a_targets.sort(key=lambda x: x[1], reverse=True)
    a1 = a_targets[0][0]
    a2 = a_targets[1][0] if len(a_targets) > 1 else None

    candidates = []

    for group_index, group, skill_index, skill in _iter_usable_skills(
            state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
    ):
        if group.delta_current.get(a1, 0) <= 0:
            continue

        for levels in _level_candidates(state, group, goal, focus_stat=a1):
            after = _apply_candidate(state, group, levels)
            if after is None:
                continue

            p = _progress(state, after, goal)
            if p["A_reduced"] <= 0:
                continue

            a1_gain = min(
                group.delta_current.get(a1, 0) * levels,
                max(0, goal.target_current.get(a1, 0) - state.current.get(a1, 0)),
            )

            a2_gain = 0
            if a2:
                a2_gain = min(
                    group.delta_current.get(a2, 0) * levels,
                    max(0, goal.target_current.get(a2, 0) - state.current.get(a2, 0)),
                )

            rare_rank = RARITY_RANK.get(skill.rare, 99)
            penalty = _experience_penalty(skill.rare, used_books_by_rare)

            score = (
                a1_gain * 12000,
                a2_gain * 7000,
                p["combo_A"] * 2000,
                p["B_reduced"] * 1000,
                -rare_rank * 800,
                -penalty,
                -p["waste"] * 600,
                -levels,
            )
            candidates.append((score, group_index, skill_index, skill, levels, after))

    return max(candidates, key=lambda x: x[0]) if candidates else None


def optimize_greedy_actions(
        initial_state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        max_iterations: int = 300,
) -> GreedyOptimizationResult:
    state = clone_state(initial_state)
    actions: List[BookAction] = []

    used_skill_ids: set[int] = set()
    used_books_by_rare: Dict[str, int] = defaultdict(int)

    best_state = clone_state(state)
    best_actions: List[BookAction] = []
    best_deficit = _deficit_score(state, goal)

    for _step in range(max_iterations):
        if _goal_reached(state, goal):
            return _make_result(True, actions, state, goal, "성공")

        cur_deficit = _deficit_score(state, goal)
        if cur_deficit < best_deficit:
            best_deficit = cur_deficit
            best_state = clone_state(state)
            best_actions = list(actions)

        chosen = None

        # 1. C가 너무 큰 경우 저등급 현재값 비급으로 먼저 보정.
        chosen = _select_reduce_c_gap(
            state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
        )

        # 2. 진급/진계 잠재력 비급 선사용.
        if chosen is None:
            chosen = _select_low_rarity_potential(
                state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare, LOW_POTENTIAL_RARITIES_1
            )

        # 3. 상승 잠재력 비급 선사용.
        if chosen is None:
            chosen = _select_low_rarity_potential(
                state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare, LOW_POTENTIAL_RARITIES_2
            )

        # 4. B가 큰 스탯 기준 잠재력 확보.
        if chosen is None:
            chosen = _select_main_potential(
                state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
            )

        # 5. 현재값 A 보강.
        if chosen is None:
            chosen = _select_current_progress(
                state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
            )

        # 6. 원래 목표 비급이 needs 때문에 막힌 경우, needs 해금용 현재값 보강.
        if chosen is None:
            chosen = _select_need_unlock_progress(
                state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
            )

        if chosen is None:
            if best_actions:
                return _make_result(
                    False,
                    best_actions,
                    best_state,
                    goal,
                    "목표를 완전히 달성하지 못했습니다. 가장 근접한 결과를 표시합니다.",
                )
            return _make_result(
                False,
                actions,
                state,
                goal,
                "현재 조건에서 진행 가능한 비급이 없습니다.",
            )

        _score, group_index, skill_index, skill, levels, after = chosen

        actions.append(_make_action(group_index, skill_index, levels))
        used_skill_ids.add(skill.id)
        used_books_by_rare[skill.rare] += 1
        state = after

    if best_actions:
        return _make_result(
            False,
            best_actions,
            best_state,
            goal,
            "반복 한도 내에서 목표를 완전히 달성하지 못했습니다. 가장 근접한 결과를 표시합니다.",
        )

    return _make_result(
        False,
        actions,
        state,
        goal,
        "반복 한도 내에서 목표에 도달하지 못했습니다.",
    )


def _find_blocked_goal_skills_by_needs(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
):
    blocked = []

    for group_index, group in enumerate(groups):
        # 원래 목표에 기여하는 그룹만 확인
        goal_related = False
        for stat in _enabled_stats(goal):
            if group.delta_current.get(stat, 0) > 0 or group.delta_potential.get(stat, 0) > 0:
                goal_related = True
                break

        if not goal_related:
            continue

        for skill_index, skill in enumerate(group.skills):
            if skill.id in used_skill_ids:
                continue

            if not _rarity_hard_allowed(skill, rarity_constraint, used_books_by_rare):
                continue

            if not _rarity_allowed_by_min_stat(state, goal, skill.rare):
                continue

            if check_needs(state, skill):
                continue

            missing = {}
            for stat, req in skill.need_current.items():
                gap = req - state.current.get(stat, 0)
                if gap > 0:
                    missing[stat] = gap

            if missing:
                blocked.append((group_index, group, skill_index, skill, missing))

    return blocked


def _build_need_unlock_stats(blocked_skills) -> dict[str, int]:
    """
    막힌 목표 비급들의 부족 요구치를 합산합니다.
    값이 클수록 해금 우선도가 높습니다.
    """
    unlock_stats = defaultdict(int)

    for _gi, _group, _si, _skill, missing in blocked_skills:
        for stat, gap in missing.items():
            unlock_stats[stat] += gap

    return dict(unlock_stats)


def _select_need_unlock_progress(
        state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        used_skill_ids: set[int],
        used_books_by_rare: Dict[str, int],
):
    """
    원래 목표 비급이 needs 때문에 막혔을 때,
    그 needs를 채우는 현재값 증가 비급을 선택합니다.
    """
    blocked = _find_blocked_goal_skills_by_needs(
        state=state,
        goal=goal,
        rarity_constraint=rarity_constraint,
        groups=groups,
        used_skill_ids=used_skill_ids,
        used_books_by_rare=used_books_by_rare,
    )

    if not blocked:
        return None

    unlock_stats = _build_need_unlock_stats(blocked)
    if not unlock_stats:
        return None

    candidates = []

    for group_index, group, skill_index, skill in _iter_usable_skills(
            state, goal, rarity_constraint, groups, used_skill_ids, used_books_by_rare
    ):
        unlock_gain = 0

        for stat, weight in unlock_stats.items():
            dc = group.delta_current.get(stat, 0)
            if dc <= 0:
                continue

            current_gap = max(0, weight)
            unlock_gain += min(dc, current_gap) * weight

        if unlock_gain <= 0:
            continue

        for levels in _level_candidates(state, group, goal):
            after = _apply_candidate(state, group, levels)
            if after is None:
                continue

            real_unlock_gain = 0
            for stat, _weight in unlock_stats.items():
                before_gap_total = 0
                after_gap_total = 0

                for _gi, _g, _si, _sk, missing in blocked:
                    if stat not in missing:
                        continue

                    req = _sk.need_current.get(stat, 0)
                    before_gap_total += max(0, req - state.current.get(stat, 0))
                    after_gap_total += max(0, req - after.current.get(stat, 0))

                real_unlock_gain += max(0, before_gap_total - after_gap_total)

            if real_unlock_gain <= 0:
                continue

            p = _progress(state, after, goal)
            rare_rank = RARITY_RANK.get(skill.rare, 99)
            penalty = _experience_penalty(skill.rare, used_books_by_rare)

            score = (
                real_unlock_gain * 15000,
                p["A_reduced"] * 3000,
                p["B_reduced"] * 2000,
                p["C_reduced"] * 1000,
                -rare_rank * 700,
                -penalty,
                -p["waste"] * 500,
                -levels,
            )

            candidates.append((score, group_index, skill_index, skill, levels, after))

    return max(candidates, key=lambda x: x[0]) if candidates else None
