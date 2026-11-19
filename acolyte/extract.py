"""Вынос аудиодорожек из mkv OBS в отдельные wav 16к моно (через PyAV)."""

from __future__ import annotations

import wave
from pathlib import Path


def audio_stream_count(mkv: Path) -> int:
    import av

    with av.open(str(mkv)) as c:
        return len(c.streams.audio)


def extract_tracks(mkv: Path, out_dir: Path, tracks: list[int]) -> list[Path]:
    """tracks — индексы аудиопотоков в порядке следования в файле (0 = Track 1)."""
    import av

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"track{n}.wav" for n in tracks]
    with av.open(str(mkv)) as c:
        audio = sorted(c.streams.audio, key=lambda s: s.index)
        for n in tracks:
            if n >= len(audio):
                raise RuntimeError(
                    f"В записи нет аудиодорожки #{n} (всего {len(audio)}). "
                    "Проверь Output → Audio Tracks в OBS."
                )
        writers = []
        try:
            resamplers = {}
            for i, n in enumerate(tracks):
                w = wave.open(str(paths[i]), "wb")
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                writers.append(w)
                resamplers[audio[n].index] = av.AudioResampler(
                    format="s16", layout="mono", rate=16000
                )
            wanted = {audio[n].index: i for i, n in enumerate(tracks)}
            for packet in c.demux([audio[n] for n in tracks]):
                si = wanted.get(packet.stream.index)
                if si is None or packet.dts is None:
                    continue
                for frame in packet.decode():
                    for rf in resamplers[packet.stream.index].resample(frame):
                        writers[si].writeframes(rf.planes[0].to_bytes())
        finally:
            for w in writers:
                w.close()
    return paths
