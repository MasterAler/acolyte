"""Обратная связь: всегда короткий писк, при наличии TTS — ещё и фраза."""

from __future__ import annotations

import threading
import time
import winsound

BEEPS = {
    "start": [(880, 100), (1318, 130)],
    "pause": [(392, 220)],
    "finish": [(659, 140), (494, 140), (330, 220)],
    "solution": [(1568, 90), (2093, 130)],
    "offtopic": [(330, 140), (262, 170)],
    "offtopic_off": [(262, 140), (392, 170)],
    "undo": [(523, 100), (392, 100)],
    "already": [(523, 80), (523, 80)],
    "error": [(196, 350)],
}

PHRASES = {
    "start": "Пишу.",
    "pause": "Пауза.",
    "finish": "Завершил. Готовлю выжимку.",
    "solution": "Решение отмечено.",
    "offtopic": "Оффтоп.",
    "offtopic_off": "В тему.",
    "undo": "Отменил.",
    "already": "Уже пишу.",
    "error": "Не поняла.",
}


class Voice:
    def __init__(self, tts_enabled=True):
        self._engine = None
        if tts_enabled:
            try:
                import pyttsx3

                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", 190)
                for v in self._engine.getProperty("voices"):
                    code = getattr(v, "id", "") + getattr(v, "name", "")
                    if "ru" in code.lower() or "irina" in code.lower() or "rus" in code.lower():
                        self._engine.setProperty("voice", v.id)
                        break
            except Exception:
                self._engine = None
        self.busy_until = 0.0

    def ack(self, kind: str):
        pattern = BEEPS.get(kind, BEEPS["error"])
        phrase = PHRASES.get(kind)
        threading.Thread(target=self._play, args=(pattern, phrase), daemon=True).start()
        if phrase:
            est = len(phrase.split()) * 0.45 + 1.0
            self.busy_until = time.time() + est + 0.4

    def is_busy(self) -> bool:
        # пока Аколит сам говорит в динамики, его может услышать микрофон
        return time.time() < self.busy_until

    def _play(self, pattern, phrase):
        for freq, ms in pattern:
            winsound.Beep(freq, ms)
        if phrase and self._engine:
            try:
                self._engine.say(phrase)
                self._engine.runAndWait()
            except Exception:
                pass
