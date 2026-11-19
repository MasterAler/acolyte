"""Матчинг голосовых команд «Аколит, …». Fuzzy: Vosk слышит «акколит», «а колит» и т.п."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

WAKE = "аколит"
WAKE_THRESHOLD = 82
INTENT_THRESHOLD = 80
MAX_UTTERANCE_CHARS = 100

INTENTS: dict[str, list[str]] = {
    "start": ["запись", "поехали", "начинаем"],
    "pause": ["стоп", "пауза", "подожди"],
    "finish": ["конец", "заверши", "финиш"],
    "solution": ["решение", "решено"],
    "offtopic": ["оффтоп", "офтоп", "не по теме", "мимо"],
    "undo": ["отмена", "отмени"],
}


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    return re.sub(r"[^\wа-я\s]", " ", t).strip()


def match(text: str) -> tuple[str, str] | None:
    """-> (intent, сырой текст) либо None, если фраза не команда."""
    if not text or len(text) > MAX_UTTERANCE_CHARS:
        return None
    norm = normalize(text)
    if not norm:
        return None
    compact = re.sub(r"\s+", "", norm)
    if fuzz.partial_ratio(WAKE, compact) < WAKE_THRESHOLD:
        return None
    best, best_score = None, 0
    for intent, keywords in INTENTS.items():
        for kw in keywords:
            score = fuzz.partial_ratio(kw, norm)
            if score > best_score:
                best, best_score = intent, score
    if best is None or best_score < INTENT_THRESHOLD:
        return "unknown", text
    return best, text


if __name__ == "__main__":
    tests = [
        ("аколит запись", "start"),
        ("акколит это решение", "solution"),
        ("а колит стоп", "pause"),
        ("аколит это оффтоп", "offtopic"),
        ("так вот аколит это решение точно", "solution"),
        ("аколет заверши встречу", "finish"),
        ("аколит отмена", "undo"),
        ("ну и как мы видим на графике рост продаж", None),
        ("глосситальный стоп некст левел", None),
        ("аколит жмыхни чёнить", "unknown"),
    ]
    for text, expected in tests:
        got = match(text)
        got_i = got[0] if got else None
        status = "OK " if got_i == expected else "FAIL"
        print(f"{status} {text!r} -> {got_i}")
        assert got_i == expected, (text, got, expected)
    print("все тесты матчера прошли")
