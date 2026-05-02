# ./app/convert_game_data.py
"""
🎯 목적: data/kr_dict.lua를 참조하여 data/martial_skills.json의 모든 중문을 한글로 치환한다.
작동 방식:
1. Lua 파일을 파싱하여 파이썬 딕셔너리로 변환
2. JSON의 모든 필드를 재귀적으로 순회하며 치환
3. ID 기반의 맵 구조로 재저장
"""

import json
import re
import os


def load_kr_dict_from_lua(file_path):
    """
    🎯 목적: Lua 테이블 형식의 파일을 파싱하여 파이썬 dict로 반환한다.
    인자: file_path (str) - kr_dict.lua 경로
    반환: dict - 한글 사전
    """
    kr_dict = {}
    # ✅ 핵심 연산: 정규표현식을 사용하여 ["중문"] = "한글" 패턴 추출
    pattern = re.compile(r'\["(.*)"\]\s*=\s*"(.*)"')

    if not os.path.exists(file_path):
        print(f"⚠️ 파일이 없습니다: {file_path}")
        return kr_dict

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                key, value = match.groups()
                kr_dict[key] = value

    # 💡 중간 출력: 사전 로드 결과 확인
    print(f"✅ KR_DICT 로드 완료: {len(kr_dict)}개의 단어 포함")
    return kr_dict


def translate_recursive(data, kr_dict):
    """
    🎯 목적: 데이터 구조를 유지하며 모든 문자열 요소를 한글로 치환한다.
    인자: data (any), kr_dict (dict)
    """
    if isinstance(data, dict):
        # 딕셔너리의 키와 값을 모두 변환하여 새 딕셔너리 생성
        return {translate_recursive(k, kr_dict): translate_recursive(v, kr_dict) for k, v in data.items()}
    elif isinstance(data, list):
        # 리스트 내부 요소 순회
        return [translate_recursive(item, kr_dict) for item in data]
    elif isinstance(data, str):
        # 문자열인 경우 사전 검색, 없으면 원문 유지
        return kr_dict.get(data, data)
    else:
        # 숫자, 불리언 등은 그대로 반환
        return data


def main():
    # 경로 설정 (상대 경로)
    lua_path = os.path.join('..', 'data', 'kr_dict.lua')
    json_path = os.path.join('..', 'data', 'martial_skills.json')
    output_path = os.path.join('..', 'data', 'martial_skills_kr.json')

    # 1. 데이터 로드
    kr_dict = load_kr_dict_from_lua(lua_path)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
    except FileNotFoundError:
        print("❌ 코드를 직접 보지 않고는 정확한 진단이 어렵지만, 현재 JSON 파일을 찾을 수 없습니다.")
        return

    # 2. 전수 변환 실행
    # ✅ 핵심 수정: 리스트 형태의 skills를 ID를 키로 하는 딕셔너리로 최적화
    processed_skills = {}
    skills_list = original_data.get("skills", [])

    for skill in skills_list:
        translated_skill = translate_recursive(skill, kr_dict)
        skill_id = translated_skill.get("id")
        processed_skills[skill_id] = translated_skill

    # 3. 최신 데이터 구조로 결과 저장
    result_wrapper = {
        "description": "한글화 및 ID 기반 최적화 데이터",
        "last_updated": original_data.get("exported_at", ""),
        "total_count": len(processed_skills),
        "skills": processed_skills
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        # ✨ 이모지를 사용하여 저장 완료 표시 (가독성 증대)
        json.dump(result_wrapper, f, ensure_ascii=False, indent=4)

    print(f"✅ 핵심 수정 완료: {output_path}에 저장되었습니다. (총 {len(processed_skills)}개)")


if __name__ == "__main__":
    main()