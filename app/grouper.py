# app/grouper.py
from collections import defaultdict
from app.models import SkillGroup


def make_group_key(skill):
    return (
        tuple(sorted(skill.delta_current.items())),
        tuple(sorted(skill.delta_potential.items()))
    )


def group_skills(skills):
    groups = defaultdict(list)

    for s in skills:
        key = make_group_key(s)
        groups[key].append(s)

    result = []
    for key, skill_list in groups.items():
        delta_current = dict(key[0])
        delta_potential = dict(key[1])

        result.append(SkillGroup(
            key=str(key),
            delta_current=delta_current,
            delta_potential=delta_potential,
            skills=skill_list
        ))

    return result
