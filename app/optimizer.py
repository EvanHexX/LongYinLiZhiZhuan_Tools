# app/optimizer.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from ortools.sat.python import cp_model

STAT_ORDER = [
    "근력", "민첩", "지력", "의지", "체질", "경맥",
    "내공", "경공", "절기", "권", "검", "도", "장병", "기문", "사술",
]


@dataclass
class StatBlock:
    current: Dict[str, int]
    potential: Dict[str, int]


@dataclass
class GoalConfig:
    enabled: Dict[str, bool]
    target_current: Dict[str, int]
    target_potential: Dict[str, int]


@dataclass
class RarityConstraint:
    enabled: Dict[str, bool]
    max_books: Dict[str, int]


@dataclass
class GroupChoice:
    group_index: int
    levels_used: int
    books_used: int


@dataclass
class OptimizationResult:
    success: bool
    choices: List[GroupChoice]
    final_state: StatBlock
    used_books_total: int
    used_levels_total: int
    overshoot_score: int
    message: str = ""


def clone_state(state: StatBlock) -> StatBlock:
    return StatBlock(
        current=dict(state.current),
        potential=dict(state.potential),
    )


def apply_group_levels(
        state: StatBlock,
        delta_current: Dict[str, int],
        delta_potential: Dict[str, int],
        levels: int,
) -> StatBlock:
    new_state = clone_state(state)

    for stat, value in delta_potential.items():
        new_state.potential[stat] = new_state.potential.get(stat, 0) + value * levels

    for stat, value in delta_current.items():
        new_cur = new_state.current.get(stat, 0) + value * levels
        max_pot = new_state.potential.get(stat, 0)
        new_state.current[stat] = min(new_cur, max_pot)

    return new_state


def build_final_state(
        initial_state: StatBlock,
        groups,
        choices: List[GroupChoice],
) -> StatBlock:
    state = clone_state(initial_state)
    for choice in choices:
        group = groups[choice.group_index]
        state = apply_group_levels(
            state,
            group.delta_current,
            group.delta_potential,
            choice.levels_used,
        )
    return state


def greedily_order_choices(
        initial_state: StatBlock,
        groups,
        choices: List[GroupChoice],
) -> Tuple[bool, List[GroupChoice], StatBlock]:
    """
    순서 유효성 검사:
    - 현재 상태에서 적용 가능한 액션만 순차 배치
    - 적용 후에도 항상 current <= potential 이어야 함
    """
    remaining = []
    for c in choices:
        if c.levels_used > 0:
            remaining.append(GroupChoice(
                group_index=c.group_index,
                levels_used=c.levels_used,
                books_used=c.books_used,
            ))

    ordered: List[GroupChoice] = []
    state = clone_state(initial_state)

    while remaining:
        progress = False

        for idx, choice in enumerate(remaining):
            group = groups[choice.group_index]

            trial = apply_group_levels(
                state,
                group.delta_current,
                group.delta_potential,
                choice.levels_used,
            )

            valid = True
            for stat in STAT_ORDER:
                if trial.current.get(stat, 0) > trial.potential.get(stat, 0):
                    valid = False
                    break

            if valid:
                ordered.append(choice)
                state = trial
                remaining.pop(idx)
                progress = True
                break

        if not progress:
            return False, [], clone_state(initial_state)

    return True, ordered, state


def optimize_groups(
        initial_state: StatBlock | None,
        goal: GoalConfig,
        rarity_constraint: RarityConstraint,
        groups,
        time_limit_seconds: int = 20,
        max_retry_cuts: int = 20,
) -> OptimizationResult:
    """
    2단계 방식:
    1) CP-SAT로 조합 최적화
    2) greedy 순서 가능성 검사
    3) 순서 불가능하면 해당 해를 금지하고 재탐색
    """

    # 희귀도 목록 수집
    rarity_names = sorted({g.skills[0].rare for g in groups})

    forbidden_solutions = []

    for _ in range(max_retry_cuts):
        model = cp_model.CpModel()

        level_vars = []
        book_vars = []

        # 그룹별 변수
        for gi, g in enumerate(groups):
            max_books_for_group = g.count
            max_levels_for_group = g.count * 10

            lv = model.NewIntVar(0, max_levels_for_group, f"levels_{gi}")
            bv = model.NewIntVar(0, max_books_for_group, f"books_{gi}")

            # levels <= books * 10
            model.Add(lv <= bv * 10)

            # books == 0 이면 levels == 0이 되도록 보조
            # lv >= bv 는 1권 사용 시 최소 1레벨 보장
            model.Add(lv >= bv)

            level_vars.append(lv)
            book_vars.append(bv)

        # 희귀도별 최대 권수
        for rare in rarity_names:
            idxs = [i for i, g in enumerate(groups) if g.skills[0].rare == rare]

            if not rarity_constraint.enabled.get(rare, True):
                for i in idxs:
                    model.Add(book_vars[i] == 0)
                continue

            max_books = rarity_constraint.max_books.get(rare, 999999)
            model.Add(sum(book_vars[i] for i in idxs) <= max_books)

        # 최종 상태 제약
        overshoot_terms = []

        for stat in STAT_ORDER:
            initial_cur = initial_state.current.get(stat, 0)
            initial_pot = initial_state.potential.get(stat, 0)

            cur_gain_expr = []
            pot_gain_expr = []

            for i, g in enumerate(groups):
                dc = g.delta_current.get(stat, 0)
                dp = g.delta_potential.get(stat, 0)

                if dc != 0:
                    cur_gain_expr.append(dc * level_vars[i])
                if dp != 0:
                    pot_gain_expr.append(dp * level_vars[i])

            final_cur = initial_cur + sum(cur_gain_expr) if cur_gain_expr else initial_cur
            final_pot = initial_pot + sum(pot_gain_expr) if pot_gain_expr else initial_pot

            # 항상 최종 current <= final potential
            model.Add(final_cur <= final_pot)

            if goal.enabled.get(stat, True):
                model.Add(final_cur >= goal.target_current.get(stat, 0))
                model.Add(final_pot >= goal.target_potential.get(stat, 0))

                over_cur = model.NewIntVar(0, 100000, f"over_cur_{stat}")
                over_pot = model.NewIntVar(0, 100000, f"over_pot_{stat}")

                model.Add(over_cur == final_cur - goal.target_current.get(stat, 0))
                model.Add(over_pot == final_pot - goal.target_potential.get(stat, 0))

                overshoot_terms.append(over_cur)
                overshoot_terms.append(over_pot)

        # 순서 불가능했던 해 금지
        for forbidden in forbidden_solutions:
            # exact same levels assignment 금지
            match_bools = []
            for i, forbidden_level in enumerate(forbidden):
                b = model.NewBoolVar(f"forbid_match_{len(match_bools)}_{i}")
                model.Add(level_vars[i] == forbidden_level).OnlyEnforceIf(b)
                model.Add(level_vars[i] != forbidden_level).OnlyEnforceIf(b.Not())
                match_bools.append(b)

            # 전부 같으면 안 됨
            model.Add(sum(match_bools) <= len(match_bools) - 1)

        total_books = model.NewIntVar(0, 100000, "total_books")
        total_levels = model.NewIntVar(0, 100000, "total_levels")
        total_overshoot = model.NewIntVar(0, 1000000, "total_overshoot")

        rarity_cost_terms = []

        model.Add(total_books == sum(book_vars))
        model.Add(total_levels == sum(level_vars))
        model.Add(total_overshoot == sum(overshoot_terms) if overshoot_terms else 0)

        for i, g in enumerate(groups):
            rare_lv = getattr(g.skills[0], "rare_lv", 0)
            rarity_cost_terms.append(rare_lv * book_vars[i])

        total_rarity_cost = model.NewIntVar(0, 1000000, "total_rarity_cost")
        model.Add(total_rarity_cost == sum(rarity_cost_terms) if rarity_cost_terms else 0)

        # 목적식: 권수 최소 > 총 단계 최소 > 초과량 최소
        # BIG1 = 10_000_000
        # BIG2 = 10_000
        # 비급 권수 최소 > 총 단계 최소 > 낮은 희귀도 우선 > 초과량 최소
        BIG1 = 10_000_000_000  # 비급 권수
        BIG2 = 10_000_000  # 총 단계
        BIG3 = 10_000  # 희귀도 비용
        objective = model.NewIntVar(0, 10 ** 12, "objective")
        # 목적함수
        # model.Add(objective == total_books * BIG1 + total_levels * BIG2 + total_overshoot)

        model.Add(
            objective ==
            total_books * BIG1 +
            total_levels * BIG2 +
            total_rarity_cost * BIG3 +
            total_overshoot
        )
        model.Minimize(objective)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_search_workers = 8

        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return OptimizationResult(
                success=False,
                choices=[],
                final_state=clone_state(initial_state),
                used_books_total=0,
                used_levels_total=0,
                overshoot_score=0,
                message="조건을 만족하는 조합을 찾지 못했습니다."
            )

        choices: List[GroupChoice] = []
        levels_signature = []

        for i in range(len(groups)):
            levels_used = solver.Value(level_vars[i])
            books_used = solver.Value(book_vars[i])
            levels_signature.append(levels_used)

            if levels_used > 0:
                choices.append(GroupChoice(
                    group_index=i,
                    levels_used=levels_used,
                    books_used=books_used,
                ))

        # 순서 가능성 검사
        order_ok, ordered_choices, final_state = greedily_order_choices(
            initial_state=initial_state,
            groups=groups,
            choices=choices,
        )

        if order_ok:
            return OptimizationResult(
                success=True,
                choices=ordered_choices,
                final_state=final_state,
                used_books_total=solver.Value(total_books),
                used_levels_total=solver.Value(total_levels),
                overshoot_score=solver.Value(total_overshoot),
                message="성공"
            )

        # 순서 불가능하면 금지 후 재시도
        forbidden_solutions.append(levels_signature)

    return OptimizationResult(
        success=False,
        choices=[],
        final_state=clone_state(initial_state),
        used_books_total=0,
        used_levels_total=0,
        overshoot_score=0,
        message="조합은 찾았지만 유효한 적용 순서를 만들지 못했습니다."
    )
