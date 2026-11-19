"""acolyte doctor: проверка всей цепочки до первого запуска."""

from __future__ import annotations

from pathlib import Path


def _ok(msg):
    print(f"  [OK]   {msg}")


def _fail(msg, hint=""):
    print(f"  [FAIL] {msg}")
    if hint:
        print(f"         {hint}")


def _warn(msg):
    print(f"  [WARN] {msg}")


def run(cfg, probe: bool = False) -> int:
    print("Аколит: осмотр пациента\n")
    fails = 0

    try:
        import sounddevice as sd

        dev = sd.default.device[0]
        if dev is None:
            _fail("Нет микрофона по умолчанию", "Проверь звуковые устройства Windows.")
            fails += 1
        else:
            _ok(f"микрофон: {sd.query_devices(dev, 'input')['name']}")
    except Exception as e:
        _fail(f"sounddevice: {e}")
        fails += 1

    if cfg.vosk_model.exists():
        _ok(f"модель Vosk: {cfg.vosk_model.name}")
    else:
        _fail(
            f"нет модели Vosk: {cfg.vosk_model}",
            "Скачай https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip "
            "и распакуй в models/. (install_models.py делает это сам)",
        )
        fails += 1

    try:
        from .obs import ObsBridge, ObsError

        obs = ObsBridge(cfg)
        obs.connect(launch=False)
        st = obs.record_status()
        _ok(f"OBS websocket: {cfg.obs_host}:{cfg.obs_port}")
        if st["active"]:
            _warn("OBS уже пишет прямо сейчас — «Аколит, запись» откажет до остановки")
        if probe:
            print("  пробная запись 3 с…")
            obs.start()
            import time

            time.sleep(3)
            f = obs.stop_and_wait_file()
            from .extract import audio_stream_count

            n = audio_stream_count(Path(f))
            if n >= 2:
                _ok(f"аудиодорожек в записи: {n}")
            else:
                _fail(
                    f"аудиодорожек только {n}",
                    "Output → Recording → Audio Tracks: включи 1 и 2; в микшере (Advanced Audio "
                    "Properties) Mic → Track 1, Desktop Audio → Track 2.",
                )
                fails += 1
            Path(f).unlink(missing_ok=True)
    except Exception as e:
        _fail(f"OBS: {e}", "Запусти OBS, включи Tools → WebSocket Server Settings (порт 4455).")
        fails += 1

    try:
        import requests

        tags = requests.get(f"{cfg.ollama_url}/api/tags", timeout=5).json()
        names = [m["name"] for m in tags.get("models", [])]
        if any(n == cfg.ollama_model or n.split(":")[0] == cfg.ollama_model.split(":")[0] for n in names):
            _ok(f"Ollama: {cfg.ollama_model}")
        else:
            _fail(f"Ollama жив, но модели {cfg.ollama_model} нет", f"Есть: {', '.join(names) or '—'}. ollama pull …")
            fails += 1
    except Exception as e:
        _fail(f"Ollama {cfg.ollama_url}: {e}", "service ollama start / ollama serve")
        fails += 1

    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        if n > 0:
            _ok(f"CUDA для faster-whisper: {n} устройств")
        else:
            _warn("CUDA недоступна — whisper пойдёт на CPU (медленно, ~1-2 ч на 4 ч аудио)")
    except Exception as e:
        _warn(f"ctranslate2: {e}")

    hub = Path.home() / ".cache" / "huggingface" / "hub"
    turbo = list(hub.glob("models--Systran--faster-whisper-large-v3-turbo")) if hub.exists() else []
    if turbo:
        _ok("модель whisper large-v3-turbo в кэше")
    else:
        _warn("whisper-модели нет в кэше: скачается при первом запуске (~1.6 ГБ)")

    print()
    if fails:
        print(f"Проблем: {fails}. Исправь и перезапусти doctor.")
        return 1
    print("Всё готово. Запускай: acolyte serve")
    return 0
