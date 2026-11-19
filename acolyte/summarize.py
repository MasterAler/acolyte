"""Выжимка: map-reduce по транскрипту через локальный Ollama."""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

MAP_SYS = """Ты — секретарь технических созвонов. Тебе дан фрагмент транскрипта встречи с таймкодами.
Говорящие: «Я» (хозяин Аколита) и «Участник» (кто-то из собеседников, имена неизвестны).
Строки «>>> РЕШЕНИЕ» — голосовые маркеры: близкий к маркеру диалог (±90 сек) содержит принятое решение.
Строки «>>> ОФФТОП НАЧАЛО/КОНЕЦ» ограничивают нерабочие разговоры.

Верни СТРОГО JSON без markdown-ограждений:
{
 "темы": ["...", ...],
 "решения": [{"что": "...", "кто": "Я|Участник|неясно", "t": "мм:сс"}],
 "задачи": [{"что": "...", "кто": "Я|Участник|неясно", "t": "мм:сс"}],
 "вопросы": ["открытые вопросы, если есть"],
 "оффтоп": ["темы оффтопа одной фразой, если попал в фрагмент"]
}
Ничего не выдумывай: только то, что сказано в тексте. Если категории пусты — пустой список."""

REDUCE_SYS = """Тебе даны JSON-выжимки последовательных фрагментов одной встречи (map-этап).
Собери из них итоговую выжимку в markdown. Требования:
1. Первая строка — «# <понятное название встречи по содержанию>».
2. Раздел «## Кратко» — 3–6 строк о сути.
3. Раздел «## Решения» — каждое решение с таймкодом, кто озвучил.
4. Раздел «## Задачи» — что нужно сделать, кому, с таймкодом.
5. Раздел «## Открытые вопросы».
6. Раздел «## Оффтоп» — одним списком тем, без деталей.
Все решения из всех фрагментов должны попасть в раздел Решения. Таймкоды сохраняй как есть.
Если про «кто» данных нет — пиши «участник». Не выдумывай имена."""


def _chat(cfg, messages, num_predict):
    body = {
        "model": cfg.ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": 16384, "num_predict": num_predict},
    }
    r = requests.post(f"{cfg.ollama_url}/api/chat", json=body, timeout=600)
    if r.status_code == 400 and "think" in r.text.lower():
        body.pop("think")
        r = requests.post(f"{cfg.ollama_url}/api/chat", json=body, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"]


def _strip(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return re.sub(r"^```(?:json|markdown)?\s*|\s*```$", "", text.strip(), flags=re.M).strip()


def _parse_json(text: str) -> dict:
    text = _strip(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _chunk(rows: list[dict], target_chars: int = 4500) -> list[list[dict]]:
    chunks, cur, size = [], [], 0
    for r in rows:
        line = json.dumps(r, ensure_ascii=False)
        if cur and size + len(line) > target_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += len(line)
    if cur:
        chunks.append(cur)
    return chunks


def _rows_to_text(rows: list[dict]) -> str:
    from .transcribe import MARKER_TITLES

    out = []
    for r in rows:
        if "marker" in r:
            out.append(f">>> {MARKER_TITLES.get(r['marker'], r['marker'].upper())}")
        else:
            out.append(f"[{r['t']:>8.1f}] {r['speaker']}: {r['text']}")
    return "\n".join(out)


def summarize_session(session_dir: Path, cfg) -> Path:
    session_dir = Path(session_dir)
    rows = [
        json.loads(l)
        for l in (session_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    if not rows:
        raise RuntimeError("transcript.jsonl пуст")

    maps = []
    for i, chunk in enumerate(_chunk(rows), 1):
        print(f"  выжимка: фрагмент {i}…")
        try:
            maps.append(_parse_json(_chat(cfg, [
                {"role": "system", "content": MAP_SYS},
                {"role": "user", "content": _rows_to_text(chunk)},
            ], num_predict=1500)))
        except Exception as e:
            print(f"  ! фрагмент {i} не разобран ({e}), пропускаю")

    if not maps:
        raise RuntimeError("ни один фрагмент не выжался")

    reduce_out = _strip(_chat(cfg, [
        {"role": "system", "content": REDUCE_SYS},
        {"role": "user", "content": "Фрагменты по порядку:\n\n" + "\n\n".join(
            f"### Фрагмент {i}\n```json\n{json.dumps(m, ensure_ascii=False, indent=1)}\n```"
            for i, m in enumerate(maps, 1)
        )},
    ], num_predict=3000))

    header = f"> Сессия: `{session_dir.name}`\n\n"
    out = session_dir / "summary.md"
    out.write_text(header + reduce_out + "\n", encoding="utf-8")
    (session_dir / "map_results.json").write_text(
        json.dumps(maps, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out
