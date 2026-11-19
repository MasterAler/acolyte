"""Транскрипция сессии: mkv OBS → два wav → faster-whisper → объединённый transcript."""

from __future__ import annotations

import json
from pathlib import Path

from .extract import extract_tracks

MARKER_TITLES = {
    "start": "НАЧАЛО ЗАПИСИ",
    "resume": "ПРОДОЛЖЕНИЕ",
    "pause": "ПАУЗА",
    "end": "КОНЕЦ",
    "solution": "РЕШЕНИЕ",
    "offtopic_on": "ОФФТОП НАЧАЛО",
    "offtopic_off": "ОФФТОП КОНЕЦ",
}


def _fmt(secs: float) -> str:
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def load_whisper(cfg):
    from faster_whisper import WhisperModel

    return WhisperModel(cfg.whisper_model, device=cfg.whisper_device, compute_type=cfg.whisper_compute)


def ensure_wavs(session_dir: Path, cfg) -> tuple[Path, Path]:
    mic, desk = session_dir / f"track{cfg.mic_track}.wav", session_dir / f"track{cfg.desktop_track}.wav"
    if not (mic.exists() and desk.exists()):
        meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
        mkv = Path(meta["obs_file"])
        extract_tracks(mkv, session_dir, [cfg.mic_track, cfg.desktop_track])
    return mic, desk


def transcribe_session(session_dir: Path, cfg, model=None) -> Path:
    session_dir = Path(session_dir)
    mic_wav, desk_wav = ensure_wavs(session_dir, cfg)
    model = model or load_whisper(cfg)

    entries = []
    for wav, speaker in ((mic_wav, "Я"), (desk_wav, "Участник")):
        segments, _info = model.transcribe(
            str(wav),
            language="ru",
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        for s in segments:
            if s.text.strip():
                entries.append(
                    {"t": round(s.start, 2), "end": round(s.end, 2), "speaker": speaker, "text": s.text.strip()}
                )

    markers = [json.loads(l) for l in (session_dir / "markers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = sorted(entries, key=lambda e: e["t"]) + [
        {"t": m["offset"], "marker": m["kind"], "wall": m["wall"]} for m in markers
    ]
    rows.sort(key=lambda r: r["t"])

    md = [f"# Транскрипт — {session_dir.name}", ""]
    with open(session_dir / "transcript.jsonl", "w", encoding="utf-8") as jf:
        for r in rows:
            tcode = _fmt(r["t"])
            if "marker" in r:
                md.append(f"`[{tcode}]` **&gt;&gt;&gt; {MARKER_TITLES.get(r['marker'], r['marker'].upper())}**")
                jf.write(json.dumps({"t": r["t"], "marker": r["marker"]}, ensure_ascii=False) + "\n")
            else:
                md.append(f"`[{tcode}]` **{r['speaker']}:** {r['text']}")
                jf.write(json.dumps({k: r[k] for k in ("t", "end", "speaker", "text")}, ensure_ascii=False) + "\n")

    out = session_dir / "transcript.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    return out
