"""Захват микрофона только для прослушивания команд (запись ведёт OBS)."""

from __future__ import annotations

import time

import numpy as np
import sounddevice as sd

TARGET_RATE = 16000
HANGOVER_S = 0.6  # сколько ещё кормить распознаватель после окончания громкого куска


class MicListener:
    def __init__(self, on_chunk, min_rms=200, debug=False):
        self.on_chunk = on_chunk  # on_chunk(bytes pcm s16le mono 16k)
        self.min_rms = min_rms    # гейт тишины/фонового шума: не кормим распознаватель мусором
        self.debug = debug        # печать уровня ДО гейта
        self._stream = None
        self._speech_until = 0.0
        self._last_print = 0.0
        self._peak = 0.0

    def start(self):
        dev = sd.default.device[0]
        if dev is None:
            raise RuntimeError("Нет устройства ввода по умолчанию")
        info = sd.query_devices(dev, "input")
        try:
            self._stream = sd.RawInputStream(
                samplerate=TARGET_RATE,
                blocksize=0,
                device=dev,
                channels=1,
                dtype="int16",
                callback=self._cb,
            )
            self._stream.start()
        except sd.PortAudioError:
            native = int(info["default_samplerate"])
            self._native_rate = native
            self._stream = sd.RawInputStream(
                samplerate=native,
                blocksize=0,
                device=dev,
                channels=1,
                dtype="int16",
                callback=self._cb_resample,
            )
            self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.close()
            self._stream = None

    def _cb(self, in_data, frames, time_info, status):
        if self.debug:
            self._show_level(in_data)
        data = bytes(in_data)  # sounddevice отдаёт cffi-буфер, vosk требует bytes
        if self._loud_enough(data):
            self.on_chunk(data)
        else:
            # тишина должна доходить до распознавателя: иначе он никогда
            # не увидит паузу и не финализирует фразу
            self.on_chunk(b"\x00" * len(data))

    def _cb_resample(self, in_data, frames, time_info, status):
        data = bytes(in_data)
        if self._loud_enough(data):
            a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            n_out = int(len(a) * TARGET_RATE / self._native_rate)
            t_out = np.arange(n_out) / TARGET_RATE
            t_in = np.arange(len(a)) / self._native_rate
            self.on_chunk(np.interp(t_out, t_in, a).astype(np.int16).tobytes())
        else:
            n_out = int(len(data) // 2 * TARGET_RATE / self._native_rate)
            self.on_chunk(b"\x00" * (n_out * 2))

    def _loud_enough(self, pcm) -> bool:
        if self.min_rms <= 0:
            return True
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if float(np.sqrt(np.mean(a * a))) >= self.min_rms:
            self._speech_until = time.monotonic() + HANGOVER_S
            return True
        return time.monotonic() < self._speech_until

    def _show_level(self, pcm) -> None:
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        self._peak = max(self._peak, float(np.sqrt(np.mean(a * a))))
        now = time.monotonic()
        if now - self._last_print >= 0.5:
            bar = "#" * int(min(self._peak, 3000) / 150)
            print(f"  [{bar:<20}] пик RMS {self._peak:>5.0f} (гейт {self.min_rms})")
            self._last_print = now
            self._peak = 0.0
