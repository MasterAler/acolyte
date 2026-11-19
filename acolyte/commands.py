"""Матчинг голосовых команд «Аколит, …». Fuzzy: Vosk слышит «акколит», «а колит» и т.п."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

WAKE = "аколит"
WAKE_AT_START_THRESHOLD = 65   # команда обычно начинается с «Аколит, …» — прощаем варинаты «о колет», «а коллетт»
WAKE_ANYWHERE_THRESHOLD = 80   # wake в середине фразы требует уверенного совпадения
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


def _wake_present(norm: str, compact: str) -> bool:
    tokens = norm.split()
    for k in (1, 2):
        head = "".join(tokens[:k])
        if head and fuzz.ratio(WAKE, head) >= WAKE_AT_START_THRESHOLD:
            return True
    return fuzz.partial_ratio(WAKE, compact) >= WAKE_ANYWHERE_THRESHOLD


def match(text: str) -> tuple[str, str] | None:
    """-> (intent, сырой текст) либо None, если фраза не команда."""
    if not text or len(text) > MAX_UTTERANCE_CHARS:
        return None
    norm = normalize(text)
    if not norm:
        return None
    compact = re.sub(r"\s+", "", norm)
    if not _wake_present(norm, compact):
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
        ("записи около пяти остановите", None),
        ("аколит жмыхни чёнить", "unknown"),
        # реальные выводы Vosk small-ru с синтезированной речи
        ("о колет запись итак обсудим план релиза на декабрь", "start"),
        ("а коллетт это решение", "solution"),
        ("выкладываем релизов в пятницу двадцатого числа", None),
    ]
    for text, expected in tests:
        got = match(text)
        got_i = got[0] if got else None
        status = "OK " if got_i == expected else "FAIL"
        print(f"{status} {text!r} -> {got_i}")
        assert got_i == expected, (text, got, expected)
    print("все тесты матчера прошли")
