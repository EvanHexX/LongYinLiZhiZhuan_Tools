# app/snapshot.py
# 이 파일은 최적화 결과를 권 단위 액션으로 분해하고,
# 실제 적용 가능한 순서로 재정렬하며,
# 특정 시점까지 적용했을 때의 상태를 재계산하는 유틸리티를 제공합니다.

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
from collections import defaultdict

from app.optimizer import STAT_ORDER, StatBlock, clone_state, apply_group_levels


@dataclass
class BookAction:
    """
    권 단위 액션 데이터입니다.

    Attributes:
        group_index: 원본 그룹 인덱스
        book_no_in_group: 해당 그룹 내 몇 번째 권인지 (1부터 시작)
        levels_used: 이 권에서 실제 사용한 단계 수 (1~10)
        default_skill_index: 그룹 내 기본 표시 스킬 인덱스 (JSON 원본 순서 기준)
    """
    group_index: int
    book_no_in_group: int
    levels_used: int
    default_skill_index: int = 0
    selected_skill_index: int = 0


def expand_choices_to_book_actions(choices, groups) -> List[BookAction]:
    """
    그룹 단위 결과를 실제 권 단위 액션 목록으로 분해합니다.

    예:
        총 단계 23 -> [10, 10, 3]

    Args:
        choices: optimizer가 반환한 GroupChoice 리스트
        groups: 그룹 목록

    Returns:
        List[BookAction]: 실제 표시 및 클릭용 액션 리스트
    """
    actions: List[BookAction] = []

    for choice in choices:
        remaining = int(choice.levels_used)
        book_no = 1

        while remaining > 0:
            use_levels = min(10, remaining)
            default_skill_index = min(book_no - 1, len(groups[choice.group_index].skills) - 1)

            actions.append(
                BookAction(
                    group_index=choice.group_index,
                    book_no_in_group=book_no,
                    levels_used=use_levels,
                    default_skill_index=default_skill_index,
                    selected_skill_index=default_skill_index,
                )
            )
            remaining -= use_levels
            book_no += 1

    return actions


def _action_is_applicable(state: StatBlock, groups, action: BookAction) -> bool:
    """
    현재 상태에서 액션을 적용할 수 있는지 검사합니다.
    - 선택된 비급의 needs 충족
    - 적용 후 current <= potential
    """
    group = groups[action.group_index]
    skill = group.skills[action.selected_skill_index]

    if not check_needs(state, skill):
        return False

    trial = apply_group_levels(
        state=state,
        delta_current=group.delta_current,
        delta_potential=group.delta_potential,
        levels=action.levels_used,
    )

    for stat in STAT_ORDER:
        if trial.current.get(stat, 0) > trial.potential.get(stat, 0):
            return False

    return True


def _action_priority_score(state: StatBlock, groups, action: BookAction, skill_index: int) -> int:
    group = groups[action.group_index]
    skill = group.skills[skill_index]

    score = 0

    for stat, val in group.delta_potential.items():
        cur = state.current.get(stat, 0)
        pot = state.potential.get(stat, 0)
        # 현재값이 잠재력에 바짝 붙은 상태라면 잠재력 증가를 더 우선
        score += val * (100 if cur >= pot else 20)

    for stat, val in group.delta_current.items():
        cur = state.current.get(stat, 0)
        pot = state.potential.get(stat, 0)

        # 현재 증가만 있는 경우엔 잠재 여유가 있을수록 조금 유리
        margin = max(0, pot - cur)
        score += min(val * action.levels_used, margin)

    # 낮은 단계 액션을 조금 우선해 끼워넣기 쉽게 함
    score += max(0, 15 - action.levels_used)

    # 고희귀도는 가능한 뒤쪽으로 weighted
    rarity_weight = 300  # TODO 나중에 설정 등으로 빼자
    rare_lv = getattr(skill, "rare_lv", 0)
    score -= rare_lv * rarity_weight

    return score


def greedily_order_book_actions(initial_state: StatBlock | None, groups, actions: List[BookAction]) -> Tuple[
    bool, List[BookAction], StatBlock]:
    """
    needs를 고려해 권 단위 액션을 정렬합니다.
    같은 그룹 안에서는 실제 사용 가능한 비급을 자동 선택합니다.
    """
    remaining = list(actions)
    ordered: List[BookAction] = []
    state = clone_state(initial_state)
    used_by_group = defaultdict(set)

    while remaining:
        candidates = []

        for action in remaining:
            skill_index = _find_applicable_skill_index(
                state=state,
                groups=groups,
                action=action,
                used_by_group=used_by_group,
            )

            if skill_index < 0:
                continue

            score = _action_priority_score(state, groups, action, skill_index)
            candidates.append((score, action, skill_index))

        if not candidates:
            return False, [], clone_state(initial_state)

        candidates.sort(key=lambda x: x[0], reverse=True)

        _, chosen, skill_index = candidates[0]
        chosen.selected_skill_index = skill_index

        group = groups[chosen.group_index]

        state = apply_group_levels(
            state=state,
            delta_current=group.delta_current,
            delta_potential=group.delta_potential,
            levels=chosen.levels_used,
        )

        used_by_group[chosen.group_index].add(skill_index)
        ordered.append(chosen)
        remaining.remove(chosen)

    return True, ordered, state


def apply_book_actions_until(initial_state: StatBlock, groups, actions: List[BookAction], count: int) -> StatBlock:
    """
    액션 리스트의 앞에서부터 count개 적용한 상태를 계산합니다.
    """
    state = clone_state(initial_state)

    for action in actions[:count]:
        group = groups[action.group_index]
        idx = getattr(action, "selected_skill_index", action.default_skill_index)

        if idx < 0 or idx >= len(group.skills):
            break

        skill = group.skills[idx]

        if not check_needs(state, skill):
            break

        state = apply_group_levels(
            state=state,
            delta_current=group.delta_current,
            delta_potential=group.delta_potential,
            levels=action.levels_used,
        )

    return state


def _find_applicable_skill_index(state: StatBlock, groups, action: BookAction, used_by_group: dict) -> int:
    """
    현재 상태에서 해당 액션에 사용할 수 있는 실제 비급 index를 찾습니다.
    같은 그룹 내 이미 사용된 비급은 제외합니다.
    """
    group = groups[action.group_index]
    used = used_by_group[action.group_index]

    candidates = []

    preferred = getattr(action, "selected_skill_index", action.default_skill_index)
    if 0 <= preferred < len(group.skills):
        candidates.append(preferred)

    for idx in range(len(group.skills)):
        if idx not in candidates:
            candidates.append(idx)

    for idx in candidates:
        if idx in used:
            continue

        skill = group.skills[idx]
        if not check_needs(state, skill):
            continue

        trial = apply_group_levels(
            state=state,
            delta_current=group.delta_current,
            delta_potential=group.delta_potential,
            levels=action.levels_used,
        )

        valid = True
        for stat in STAT_ORDER:
            if trial.current.get(stat, 0) > trial.potential.get(stat, 0):
                valid = False
                break

        if valid:
            return idx

    return -1


def check_needs(state: StatBlock, skill) -> bool:
    """
    현재 상태가 해당 비급의 요구치를 만족하는지 검사
    """
    for stat, req in skill.need_current.items():
        if state.current.get(stat, 0) < req:
            return False
    return True
