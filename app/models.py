# app/models.py
# 비급 최적화 도구에서 사용하는 데이터 모델 정의 파일입니다.

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Skill:
    """
    개별 비급 데이터입니다.
    """
    id: int
    name: str
    rare: str
    rare_lv: int
    force_name: str
    type_name: str
    needs: str
    need_current: dict[str, int]
    delta_current: dict
    delta_potential: dict
    desc: str = ""
    range_min: int = 0
    range_max: int = 0
    dmg_range_min: int = 0
    dmg_range_max: int = 0
    base_dmg: float = 0.0
    mana_cost: float = 0.0
    upgrade_total: int = 0
    dmg_bonus: dict[str, float] = field(default_factory=dict)
    equip_bonus: dict[str, float] = field(default_factory=dict)
    use_effect: dict[str, float] = field(default_factory=dict)
    atk_posture: list[int] = field(default_factory=lambda: [0] * 6)
    def_posture: list[int] = field(default_factory=lambda: [0] * 6)
    weapon: str = ""
    max_use: int = 0
    #  JSON 저장 시 리스트 형태로 유지
    visual_effect: List[str] = field(default_factory=list)

    def __post_init__(self):
        # 만약 생성 시점에 문자열 "text1, text2"가 들어온다면 리스트로 자동 변환
        if isinstance(self.visual_effect, str):
            self.visual_effect = [item.strip() for item in self.visual_effect.split(',') if item.strip()]

        # 리스트 길이 교정
        self.atk_posture = self._ensure_six_elements(self.atk_posture)
        self.def_posture = self._ensure_six_elements(self.def_posture)

    @staticmethod
    def _ensure_six_elements(lst: list) -> list:
        """리스트가 비었거나 길이가 6이 아니면 기본 리스트 반환"""
        if not lst or len(lst) != 6:
            return [0] * 6
        return lst


@dataclass
class SkillGroup:
    """
    동일 성장치를 가진 비급 그룹입니다.
    """
    key: str
    delta_current: dict
    delta_potential: dict
    skills: list

    @property
    def count(self):
        return len(self.skills)
