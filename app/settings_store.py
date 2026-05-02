# app/settings_store.py
# 환경설정 파일을 읽고 저장하는 모듈입니다.

import json
from pathlib import Path


CONFIG_DIR = Path("config")
SETTINGS_PATH = CONFIG_DIR / "settings.json"


DEFAULT_SETTINGS = {
    "db_path": "data/skills_kr.db",
    "custom_id_min": 1051,
}


def load_settings() -> dict:
    """
    환경설정을 로드합니다.
    없으면 기본값을 반환합니다.
    """
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)

    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return dict(DEFAULT_SETTINGS)

    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def save_settings(settings: dict) -> None:
    """
    환경설정을 파일로 저장합니다.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    with SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)