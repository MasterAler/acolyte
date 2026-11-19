"""Vosk: стриминговое распознавание микрофона ради команд. Отдаём только финальные фразы."""

from __future__ import annotations

import json

MIN_WORDS_CONF = 0.25  # ниже — галлюцинации на шуме
MIN_TEXT_LEN = 4       # короче 4 букв команды быть не может


class Ear:
    def __init__(self, model_dir, on_raw=None):
        from vosk import KaldiRecognizer, Model

        self._rec = KaldiRecognizer(Model(str(model_dir)), 16000)
        self._rec.SetWords(True)
        self.on_raw = on_raw  # диагностика: колбэк на каждый финал до фильтров

    def feed(self, pcm: bytes) -> str | None:
        """Возвращает текст финальной фразы (может быть пустым), None — пока фраза не закончена."""
        if self._rec.AcceptWaveform(pcm):
            return self._filter(self._rec.Result(), self.on_raw)
        return None

    def flush(self) -> str:
        return self._filter(self._rec.FinalResult(), self.on_raw)

    @staticmethod
    def _filter(raw: str, on_raw=None) -> str:
        data = json.loads(raw)
        if on_raw:
            on_raw(data)
        text = (data.get("text") or "").strip()
        if len(text.replace(" ", "")) < MIN_TEXT_LEN:
            return ""
        words = data.get("result") or []
        if words:
            conf = sum(w.get("conf", 1.0) for w in words) / len(words)
            if conf < MIN_WORDS_CONF:
                return ""
        return text
