import sys
import os


def resource_path(relative_path):
    """리소스의 절대 경로를 반환합니다."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
