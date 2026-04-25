# app/loaders.py
import json


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


__all__ = ["load_json"]
