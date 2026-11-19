"""Захват микрофона только для прослушивания команд (запись ведёт OBS)."""

from __future__ import annotations

import numpy as np
import sounddevice as sd

TARGET_RATE = 16000


class MicListener:
    def __init__(self, on_chunk, verbose=False):
        self.on_chunk = on_chunk  # on_chunk(bytes pcm s16le mono 16k)
        self.verbose = verbose
        self._stream = None

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
        self.on_chunk(in_data)

    def _cb_resample(self, in_data, frames, time_info, status):
        a = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
        n_out = int(len(a) * TARGET_RATE / self._native_rate)
        t_out = np.arange(n_out) / TARGET_RATE
        t_in = np.arange(len(a)) / self._native_rate
        self.on_chunk(np.interp(t_out, t_in, a).astype(np.int16).tobytes())
