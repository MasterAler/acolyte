from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    obs_host: str = "localhost"
    obs_port: int = 4455
    obs_password: str = ""
    obs_exe: str = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"
    obs_launch_timeout: float = 20.0

    mic_track: int = 0
    desktop_track: int = 1

    vosk_model: Path = PROJECT_ROOT / "models" / "vosk-model-small-ru-0.22"
    sessions_dir: Path = PROJECT_ROOT / "sessions"

    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cuda"
    whisper_compute: str = "int8_float16"

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b"

    voice_tts: bool = True
    hotkeys: bool = False

    confluence_url: str = ""
    confluence_user: str = ""
    confluence_token: str = ""
    confluence_space: str = ""
    confluence_parent_id: str = ""

    rag_jsonl: Path = Path.home() / ".codex" / "tools" / "memory-rag" / ".data" / "acolyte.jsonl"

    _PREFIX = {
        "obs": "obs_",
        "tracks": "",
        "asr": "whisper_",
        "llm": "ollama_",
        "misc": "",
        "confluence": "confluence_",
    }
    _SPECIAL = {("tracks", "mic"): "mic_track", ("tracks", "desktop"): "desktop_track"}

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        cfg = cls()
        p = path or PROJECT_ROOT / "acolyte.toml"
        if p.exists():
            with open(p, "rb") as f:
                data = tomllib.load(f)
            flat: dict = {}
            for sect, items in data.items():
                if isinstance(items, dict):
                    for k, v in items.items():
                        key = cls._SPECIAL.get((sect, k)) or cls._PREFIX[sect] + k
                        flat[key] = v
                else:
                    flat[sect] = items
            for k, v in flat.items():
                if hasattr(cfg, k):
                    cur = getattr(cfg, k)
                    if isinstance(cur, Path) and not isinstance(v, Path):
                        v = Path(v)
                    setattr(cfg, k, v)
        env = os.environ
        if env.get("ACOLYTE_OBS_PASSWORD"):
            cfg.obs_password = env["ACOLYTE_OBS_PASSWORD"]
        if env.get("ACOLYTE_OLLAMA_MODEL"):
            cfg.ollama_model = env["ACOLYTE_OLLAMA_MODEL"]
        cfg.sessions_dir.mkdir(parents=True, exist_ok=True)
        return cfg
