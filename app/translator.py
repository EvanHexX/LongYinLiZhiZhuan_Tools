# app/translator.py
import re


def load_kr_dict(path):
    mapping = {}

    pattern = re.compile(r'\["(.+?)"\]\s*=\s*"(.+?)"')

    with open(path, encoding="utf-8") as f:
        for line in f:
            m = pattern.search(line)
            if m:
                mapping[m.group(1)] = m.group(2)

    return mapping


def translate(text, mapping):
    if not text:
        return text

    # 긴 키부터 치환 (CE 방식)
    for k in sorted(mapping.keys(), key=len, reverse=True):
        text = text.replace(k, mapping[k])

    return text
