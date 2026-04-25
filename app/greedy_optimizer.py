# app/greedy_optimizer.py
# 현재 상태에서 실제로 배울 수 있는 비급만 후보로 삼아 반복 선택하는 greedy 최적화 엔진입니다.

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Tuple
from collections import defaultdict

from app.optimizer import StatBlock, GoalConfig, RarityConstraint, clone_state, apply_group_levels, STAT_ORDER
from app.snapshot import BookAction, check_needs


@dataclass
class GreedyOptimizationResult:
    success: bool
    actions: List[BookAction]
    final_state: StatBlock
    used_books_total: int
    used_levels_total: int
    overshoot_score: int
    message: str = ""


def _goal_reached(state: StatBlock, goal: GoalConfig) -> bool:
    for stat in STAT_ORDER:
        if not goal.enabled.get(stat, True):
            continue

        if state.current.get(stat, 0) < goal.target_current.get(stat, 0):
            return False

        if state.potential.get(stat, 0) < goal.target_potential.get(stat, 0):
            return False

    return True


def _deficit_score(state: StatBlock, goal: GoalConfig) -> int:
    """
    목표까지 남은 부족량 점수입니다.
    낮을수록 좋습니다.
    """
    score = 0

    for stat in STAT_ORDER:
        if not goal.enabled.get(stat, True):
            continue

        score += max(0, goal.target_current.get(stat, 0) - state.current.get(stat, 0))
        score += max(0, goal.target_potential.get(stat, 0) - state.potential.get(stat, 0))

    return score


def _overshoot_score(state: StatBlock, goal: GoalConfig) -> int:
    score = 0

    for stat in STAT_ORDER:
        if not goal.enabled.get(stat, True):
            continue

        score += max(0, state.current.get(stat, 0) - goal.target_current.get(stat, 0))
        score += max(0, state.potential.get(stat, 0) - goal.target_potential.get(stat, 0))

    return score


def _state_valid(state: StatBlock) -> bool:
    for stat in STAT_ORDER:
        if state.current.get(stat, 0) > state.potential.get(stat, 0):
            return False
    return True


def _candidate_score(
        before: StatBlock,
        after: StatBlock,
        goal: GoalConfig,
        skill,
        levels: int,
) -> Tuple[int, int, int, int]:
    """
    후보 정렬 점수입니다.
    tuple은 큰 값이 우선입니다.

    1. 목표 부족량 감소량
    2. 목표 항목에 직접 기여한 성장량
    3. 낮은 희귀도 우선
    4. 적은 오버슈트 우선
    """
    before_deficit = _deficit_score(before, goal)
    after_deficit = _deficit_score(after, goal)
    deficit_reduced = before_deficit - after_deficit

    useful_gain = 0
    for stat in STAT_ORDER:
        if not goal.enabled.get(stat, True):
            continue

        cur_gain = max(0, after.current.get(stat, 0) - before.current.get(stat, 0))
        pot_gain = max(0, after.potential.get(stat, 0) - before.potential.get(stat, 0))

        # 목표를 이미 넘긴 항목의 성장은 낮게 봄
        if before.current.get(stat, 0) < goal.target_current.get(stat, 0):
            useful_gain += cur_gain * 2
        if before.potential.get(stat, 0) < goal.target_potential.get(stat, 0):
            useful_gain += pot_gain * 2

    rare_lv = getattr(skill, "rare_lv", 0)
    over = _overshoot_score(after, goal)

    # Python sort reverse=True 기준
    return (
        deficit_reduced * 1000,
        useful_gain * 100,
        -rare_lv * 50,
        -over,
    )


def optimize_greedy_actions(
        initial_state: StatBlock,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        max_iterations: int = 300,
) -> GreedyOptimizationResult:
    """
    needs를 자연스럽게 반영하는 greedy 최적화입니다.

    매 반복:
    1. 현재 상태에서 needs를 만족하는 비급만 후보
    2. 아직 사용하지 않은 실제 비급만 후보
    3. 희귀도 제한을 넘지 않는 후보만 선택
    4. 1~10단계 중 가장 점수가 좋은 사용량 선택
    5. 상태 갱신 후 반복
    """
    state = clone_state(initial_state)
    actions: List[BookAction] = []

    used_skill_ids = set()
    used_books_by_rare: Dict[str, int] = defaultdict(int)

    # 희귀도 사용 금지/상한 초기화
    for rare, enabled in rarity_constraint.enabled.items():
        if not enabled:
            # enabled False는 max 0과 동일하게 처리
            rarity_constraint.max_books[rare] = 0

    for _ in range(max_iterations):
        if _goal_reached(state, goal):
            return GreedyOptimizationResult(
                success=True,
                actions=actions,
                final_state=state,
                used_books_total=len(actions),
                used_levels_total=sum(a.levels_used for a in actions),
                overshoot_score=_overshoot_score(state, goal),
                message="성공",
            )

        candidates = []

        for group_index, group in enumerate(groups):
            for skill_index, skill in enumerate(group.skills):
                if skill.id in used_skill_ids:
                    continue

                rare = skill.rare
                max_books = rarity_constraint.max_books.get(rare, 999999)
                if used_books_by_rare[rare] >= max_books:
                    continue

                if not check_needs(state, skill):
                    continue

                # 이 비급을 1~10단계 중 몇 단계까지 읽을지 평가
                best_for_skill = None

                for levels in range(1, 11):
                    after = apply_group_levels(
                        state=state,
                        delta_current=group.delta_current,
                        delta_potential=group.delta_potential,
                        levels=levels,
                    )

                    if not _state_valid(after):
                        continue

                    score = _candidate_score(
                        before=state,
                        after=after,
                        goal=goal,
                        skill=skill,
                        levels=levels,
                    )

                    unlock_score = _need_unlock_score(
                        before=state,
                        after=after,
                        goal=goal,
                        groups=groups,
                        used_skill_ids=used_skill_ids,
                    )

                    # 목표도 줄이지 못하고, needs 해금에도 도움 안 되면 제외
                    if score[0] <= 0 and unlock_score <= 0:
                        continue

                    score = (
                        score[0],
                        unlock_score,
                        score[1],
                        score[2],
                        score[3],
                    )

                    if best_for_skill is None or score > best_for_skill[0]:
                        best_for_skill = (score, levels, after)

                if best_for_skill is None:
                    continue

                score, levels, after = best_for_skill
                candidates.append((score, group_index, skill_index, skill, levels, after))

        if not candidates:
            return GreedyOptimizationResult(
                success=False,
                actions=actions,
                final_state=state,
                used_books_total=len(actions),
                used_levels_total=sum(a.levels_used for a in actions),
                overshoot_score=_overshoot_score(state, goal),
                message="현재 상태와 needs 조건에서 목표를 더 진행할 수 있는 비급이 없습니다.",
            )

        candidates.sort(key=lambda x: x[0], reverse=True)

        _score, group_index, skill_index, skill, levels, after = candidates[0]

        action = BookAction(
            group_index=group_index,
            book_no_in_group=1,
            levels_used=levels,
            default_skill_index=skill_index,
            selected_skill_index=skill_index,
        )

        actions.append(action)
        used_skill_ids.add(skill.id)
        used_books_by_rare[skill.rare] += 1
        state = after

    return GreedyOptimizationResult(
        success=False,
        actions=actions,
        final_state=state,
        used_books_total=len(actions),
        used_levels_total=sum(a.levels_used for a in actions),
        overshoot_score=_overshoot_score(state, goal),
        message="반복 한도 내에서 목표에 도달하지 못했습니다.",
    )


def _need_unlock_score(before: StatBlock, after: StatBlock, goal: GoalConfig, groups, used_skill_ids: set) -> int:
    """
    현재는 못 배우지만 목표 달성에 도움이 되는 비급들의 needs를
    얼마나 풀어주는지 계산합니다.
    """
    score = 0

    for group in groups:
        for skill in group.skills:
            if skill.id in used_skill_ids:
                continue

            # 이 비급이 목표에 기여하는지 확인
            useful = False
            for stat in STAT_ORDER:
                if not goal.enabled.get(stat, True):
                    continue

                if group.delta_current.get(stat, 0) > 0 and before.current.get(stat, 0) < goal.target_current.get(stat,
                                                                                                                  0):
                    useful = True

                if group.delta_potential.get(stat, 0) > 0 and before.potential.get(stat, 0) < goal.target_potential.get(
                        stat, 0):
                    useful = True

            if not useful:
                continue

            # needs 부족분이 얼마나 줄었는지 계산
            for stat, req in skill.need_current.items():
                before_gap = max(0, req - before.current.get(stat, 0))
                after_gap = max(0, req - after.current.get(stat, 0))

                if before_gap > after_gap:
                    score += (before_gap - after_gap) * 500

    return score
