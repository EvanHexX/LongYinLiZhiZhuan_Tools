# app/models.py
# 비급 최적화 도구에서 사용하는 데이터 모델 정의 파일입니다.

from dataclasses import dataclass


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