"""Мост к OBS через obs-websocket. Запись ведёт OBS, Аколит только командует."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path


class ObsError(RuntimeError):
    pass


class ObsBridge:
    def __init__(self, cfg):
        self.cfg = cfg
        self._req = None
        self._evt = None
        self._last_output_path: str | None = None
        self._state_lock = threading.Lock()

    def connect(self, launch: bool = True) -> None:
        import obsws_python

        if not self._try_connect(obsws_python):
            if not launch or not Path(self.cfg.obs_exe).exists():
                raise ObsError(
                    "OBS недоступен. Запусти OBS (Tools → WebSocket Server Settings → Enable) "
                    "или укажи obs_exe в acolyte.toml."
                )
            subprocess.Popen(
                [self.cfg.obs_exe, "--disable-shutdown-check"],
                cwd=Path(self.cfg.obs_exe).parent,
            )
            deadline = time.time() + self.cfg.obs_launch_timeout
            while time.time() < deadline:
                if self._try_connect(obsws_python):
                    break
                time.sleep(1.0)
            else:
                raise ObsError(f"OBS не поднялся за {self.cfg.obs_launch_timeout} с")

        evc = obsws_python.EventClient(
            host=self.cfg.obs_host, port=self.cfg.obs_port, password=self.cfg.obs_password
        )

        @evc.event.on("RecordStateChanged")
        def _on_record(m):
            data = getattr(m, "event_data", {}) or {}
            path = data.get("outputPath") or data.get("output_path")
            if path:
                with self._state_lock:
                    self._last_output_path = path

        self._evt = evc

    def _try_connect(self, obsws_python) -> bool:
        try:
            self._req = obsws_python.ReqClient(
                host=self.cfg.obs_host,
                port=self.cfg.obs_port,
                password=self.cfg.obs_password,
                timeout=5,
            )
            return True
        except Exception:
            self._req = None
            return False

    @property
    def req(self):
        if self._req is None:
            raise ObsError("OBS не подключён")
        return self._req

    def record_status(self) -> dict:
        st = self.req.get_record_status()
        return {
            "active": bool(st.active),
            "paused": bool(st.paused),
            "duration_ms": getattr(st, "duration", 0),
        }

    def start(self):
        self.req.start_record()

    def pause(self):
        self.req.pause_record()

    def resume(self):
        self.req.resume_record()

    def stop_and_wait_file(self, timeout: float = 30.0) -> Path:
        with self._state_lock:
            self._last_output_path = None
        self.req.stop_record()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._state_lock:
                if self._last_output_path:
                    p = Path(self._last_output_path)
                    # OBS может отдать путь до закрытия файла: ждём стабильного размера
                    if self._file_stable(p):
                        return p
            time.sleep(0.5)
        raise ObsError(f"Не дождались файла записи за {timeout} с")

    def _file_stable(self, p: Path) -> bool:
        try:
            if not p.exists():
                return False
            s1 = p.stat().st_size
            time.sleep(0.6)
            s2 = p.stat().st_size
            return s1 == s2 and s2 > 0
        except OSError:
            return False
