# search_cli.py
# 조건(needs)과 상승치(upgrade_text)를 포함한 최종 검색 스크립트 🚀

import json
import os
from app.settings_store import load_settings
from app.translator import load_kr_dict, translate
from app.normalizer import normalize_skill


def load_data():
    """데이터를 로드하고 필요한 필드들을 번역하여 리스트로 반환합니다."""
    settings = load_settings()
    mapping = load_kr_dict(settings["dict_path"])

    if not os.path.exists(settings["json_path"]):
        print(f"❌ 파일을 찾을 수 없습니다: {settings['json_path']}")
        return []

    try:
        with open(settings["json_path"], "r", encoding="utf-8") as f:
            full_data = json.load(f)

        # JSON 구조: {"skills": [...]} 대응
        items = full_data.get("skills", [])
    except Exception as e:
        print(f"❌ JSON 로드 실패: {e}")
        return []

    skills = []
    for raw in items:
        if not isinstance(raw, dict): continue

        try:
            # ✅ 번역 적용
            raw["name"] = translate(raw.get("name", ""), mapping)
            raw["force_name"] = translate(raw.get("force_name", "江湖"), mapping)
            raw["type_name"] = translate(raw.get("type_name", "기타"), mapping)
            raw["rare_name"] = translate(raw.get("rare_name", ""), mapping)

            # ✅ 조건(needs) 번역: "内功10" -> "내공10"
            raw["needs"] = translate(raw.get("needs", ""), mapping)

            # ✅ 상승치(upgrade_text) 번역: "内功+1" -> "내공+1"
            raw["upgrade_text"] = translate(raw.get("upgrade_text", ""), mapping)

            # normalizer를 통해 Skill 객체 생성 (기존 로직 유지)
            skill_obj = normalize_skill(raw)

            # ✅ Skill 객체에 번역된 upgrade_text 주입 (출력용)
            # normalize_skill 결과물에 upgrade_text가 없을 경우를 대비해 직접 추가합니다.
            skill_obj.upgrade_display = raw["upgrade_text"] if raw["upgrade_text"] else "정보 없음"

            skills.append(skill_obj)
        except Exception:
            continue

    return skills


def filter_data(skills, criteria):
    """다중 조건을 지원하는 필터링 로직"""
    filtered = []
    for s in skills:
        if criteria['force'] and not any(f in s.force_name for f in criteria['force']): continue
        if criteria['type'] and not any(t in s.type_name for t in criteria['type']): continue
        if criteria['rare'] and not any(r in s.rare for r in criteria['rare']): continue
        # 조건(needs) 필터링
        if criteria['need'] and not any(n in s.needs for n in criteria['need']): continue
        filtered.append(s)
    return filtered


def main():
    print("=== 📚 비급 데이터 조건 검색기 ===")

    skills = load_data()
    if not skills:
        print("⚠️ 데이터를 불러오지 못했습니다.")
        return

    print(f"✅ 총 {len(skills)}개의 비급 데이터 로드 완료.")
    print("※ 조건 미입력 시 전체 검색 / 다중 조건은 쉼표(,) 사용")
    print("-" * 80)

    f_in = input("1. 출처 (문파): ").strip()
    t_in = input("2. 종류 (검법/내공 등): ").strip()
    r_in = input("3. 등급: ").strip()
    n_in = input("4. 필요 조건 (예: 내공, 근력): ").strip()

    criteria = {
        'force': [i.strip() for i in f_in.split(',') if i.strip()],
        'type': [i.strip() for i in t_in.split(',') if i.strip()],
        'rare': [i.strip() for i in r_in.split(',') if i.strip()],
        'need': [i.strip() for i in n_in.split(',') if i.strip()]
    }

    results = filter_data(skills, criteria)

    print(f"\n🔍 검색 결과: {len(results)}건")
    print("=" * 140)
    # 열 너비를 조건과 상승치에 맞춰 조정
    print(f"{'출처':<12} | {'등급':<8} | {'종류':<10} | {'이름':<20} | {'조건':<15} | {'상승치'}")
    print("-" * 140)

    for s in results:
        # s.needs는 이미 번역된 상태, s.upgrade_display는 위에서 주입한 번역본 사용
        needs_str = s.needs if s.needs else "-"
        print(
            f"{s.force_name:<12} | {s.rare:<8} | {s.type_name:<10} | {s.name:<20} | {needs_str:<15} | {s.upgrade_display}")


if __name__ == "__main__":
    main()