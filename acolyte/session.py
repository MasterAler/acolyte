"""Состояние живой сессии: маркеры и пересчёт «настенных» времён в таймкоды файла.

OBS на паузе не пишет в файл, поэтому смещение маркера = активное время записи,
а не календарная разница. Паузы, нажатые руками в OBS, эту математику ломают —
в сессии фиксируются только паузы, отданные Аколитом.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

STRUCTURAL = {"start", "resume", "pause", "end"}


class SessionState:
    def __init__(self, sessions_dir: Path):
        self.dir = sessions_dir / datetime.now().strftime("%Y-%m-%d_%H-%M_%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.markers_path = self.dir / "markers.jsonl"
        self.meta_path = self.dir / "meta.json"
        self.markers: list[dict] = []

        self.recording = False
        self.paused = False
        self.finished = False
        self.offtopic = False
        self._rec_started_at: float | None = None
        self._pause_started_at: float | None = None
        self._active_before_pause = 0.0
        self.obs_file: str | None = None
        self.title_hint: str | None = None

    # --- тайминги -----------------------------------------------------------

    def active_seconds(self) -> float:
        # во время паузы _rec_started_at обнулен, но накопленное время валидно
        if self._rec_started_at is not None:
            return self._active_before_pause + (time.time() - self._rec_started_at)
        return self._active_before_pause

    def _fmt(self, secs: float) -> str:
        secs = max(0, int(secs))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    # --- события ------------------------------------------------------------

    def add_marker(self, kind: str, text: str = "") -> dict:
        mk = {
            "wall": datetime.now().isoformat(timespec="seconds"),
            "offset": round(self.active_seconds(), 2),
            "tcode": self._fmt(self.active_seconds()),
            "kind": kind,
            "text": text,
        }
        self.markers.append(mk)
        with open(self.markers_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(mk, ensure_ascii=False) + "\n")
        return mk

    def undo_last(self) -> dict | None:
        for i in range(len(self.markers) - 1, -1, -1):
            if self.markers[i]["kind"] not in STRUCTURAL:
                mk = self.markers.pop(i)
                self._rewrite()
                return mk
        return None

    def _rewrite(self):
        with open(self.markers_path, "w", encoding="utf-8") as f:
            for mk in self.markers:
                f.write(json.dumps(mk, ensure_ascii=False) + "\n")

    def save_meta(self):
        data = {
            "obs_file": self.obs_file,
            "offtopic_at_end": self.offtopic,
            "markers": self.markers,
        }
        self.meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- переходы (вызывает сервер после успешной команды OBS) ---------------

    def on_start(self):
        self.recording = True
        self.paused = False
        self._rec_started_at = time.time()
        self._active_before_pause = 0.0
        self.add_marker("start")

    def on_resume(self):
        if self._pause_started_at is not None:
            self._active_before_pause += time.time() - self._pause_started_at
            self._pause_started_at = None
        self._rec_started_at = time.time()
        self.paused = False
        self.add_marker("resume")

    def on_pause(self):
        if self._rec_started_at is not None:
            self._active_before_pause += time.time() - self._rec_started_at
        self._pause_started_at = time.time()
        self._rec_started_at = None
        self.paused = True
        self.add_marker("pause")

    def on_end(self, obs_file: str):
        if self._rec_started_at is not None:
            self._active_before_pause += time.time() - self._rec_started_at
        self._rec_started_at = None
        self._pause_started_at = None
        self.recording = False
        self.paused = False
        self.finished = True
        self.obs_file = obs_file
        self.add_marker("end")
        self.save_meta()
