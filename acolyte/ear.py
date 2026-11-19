"""Vosk: стриминговое распознавание микрофона ради команд. Отдаём только финальные фразы."""

from __future__ import annotations

import json


class Ear:
    def __init__(self, model_dir):
        from vosk import KaldiRecognizer, Model

        self._rec = KaldiRecognizer(Model(str(model_dir)), 16000)
        self._rec.SetWords(False)

    def feed(self, pcm: bytes) -> str | None:
        """Возвращает текст финальной фразы (может быть пустым), None — пока фраза не закончена."""
        if self._rec.AcceptWaveform(pcm):
            return json.loads(self._rec.Result()).get("text", "")
        return None

    def flush(self) -> str:
        return json.loads(self._rec.FinalResult()).get("text", "")
