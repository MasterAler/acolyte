from __future__ import annotations

import argparse
import queue
import sys
import time
from pathlib import Path

from .commands import match
from .config import Config
from .session import SessionState


def _pipeline(session_dir: Path, cfg):
    from .summarize import summarize_session
    from .transcribe import transcribe_session

    print("Транскрипция (whisper)…")
    transcript = transcribe_session(session_dir, cfg)
    print(f"  -> {transcript}")
    print("Выжимка (ollama)…")
    summary = summarize_session(session_dir, cfg)
    print(f"  -> {summary}\n")
    print(summary.read_text(encoding="utf-8"))


def _dispatch(intent, raw, sess, obs, voice, cfg, no_summarize) -> None:
    if intent == "start":
        st = obs.record_status()
        if st["active"] and not sess.recording:
            print("! OBS уже пишет, но не по команде Аколита — останови запись в OBS и повтори")
            voice.ack("error")
            return
        if sess.recording and not sess.paused:
            voice.ack("already")
            return
        if sess.paused:
            if st["active"] and st["paused"] is False:
                print("! рассинхрон: OBS уже пишет — продолжаю без resume")
                sess.on_resume()
            elif st["active"] is False:
                print("! запись в OBS остановилась; стартую заново НОВЫМ файлом (старый останется в папке записи)")
                obs.start()
                sess.on_resume()
            else:
                obs.resume()
                sess.on_resume()
        elif st["paused"]:
            print("! пауза ставилась руками в OBS — таймкоды маркеров могут уехать")
            obs.resume()
            sess.on_resume()
        else:
            obs.start()
            sess.on_start()
        voice.ack("start")
        print(f"[{time.strftime('%H:%M:%S')}] пишем")

    elif intent == "pause":
        if sess.recording and not sess.paused:
            if sess.offtopic:
                sess.add_marker("offtopic_off")
                sess.offtopic = False
            obs.pause()
            sess.on_pause()
            voice.ack("pause")
            print(f"[{time.strftime('%H:%M:%S')}] пауза")
        else:
            voice.ack("already")

    elif intent == "finish":
        if not sess.recording:
            voice.ack("error")
            print("! сейчас не пишем")
            return
        if sess.offtopic:
            sess.add_marker("offtopic_off")
            sess.offtopic = False
        print("Останавливаю запись…")
        f = obs.stop_and_wait_file()
        sess.on_end(str(f))
        voice.ack("finish")
        print(f"Запись: {f}")
        print(f"Сессия: {sess.dir}")
        if no_summarize:
            print(f"Позже: acolyte transcribe {sess.dir} && acolyte summarize {sess.dir}")
        else:
            try:
                _pipeline(sess.dir, cfg)
            except Exception as e:
                print(f"! пайплайн упал: {e}\n  повторить: acolyte summarize {sess.dir}")

    elif intent == "solution":
        if not sess.recording:
            voice.ack("error")
            print("! скажи сначала «Аколит, запись»")
            return
        if sess.offtopic:
            sess.add_marker("offtopic_off")
            sess.offtopic = False
        mk = sess.add_marker("solution", raw)
        voice.ack("solution")
        print(f"[{mk['tcode']}] МАРКЕР: РЕШЕНИЕ")

    elif intent == "offtopic":
        if not sess.recording:
            voice.ack("error")
            return
        if sess.offtopic:
            voice.ack("already")
            return
        sess.offtopic = True
        mk = sess.add_marker("offtopic_on", raw)
        voice.ack("offtopic")
        print(f"[{mk['tcode']}] флуд начался")

    elif intent == "ontopic":
        if not sess.offtopic:
            voice.ack("already")
            return
        sess.offtopic = False
        mk = sess.add_marker("offtopic_off", raw)
        voice.ack("offtopic_off")
        print(f"[{mk['tcode']}] флуд окончен")

    elif intent == "undo":
        mk = sess.undo_last()
        if mk:
            if mk["kind"] == "offtopic_on":
                sess.offtopic = False
            elif mk["kind"] == "offtopic_off":
                sess.offtopic = True
            voice.ack("undo")
            print(f"снят маркер {mk['kind']} @ {mk['tcode']}")
        else:
            voice.ack("error")
            print("маркеров нет")

    else:
        voice.ack("error")
        print(f"  команда не распознана: {raw!r}")


def cmd_serve(cfg, verbose=False, no_summarize=False) -> int:
    from .ear import Ear
    from .mic import MicListener
    from .obs import ObsBridge, ObsError
    from .voice import Voice

    try:
        obs = ObsBridge(cfg)
        obs.connect(launch=True)
    except ObsError as e:
        print(f"! {e}")
        return 1
    voice = Voice(cfg.voice_tts)
    try:
        ear = Ear(cfg.vosk_model)
    except Exception as e:
        print(f"! модель Vosk не загрузилась: {e}\n  см. install_models.py")
        return 1

    sess = SessionState(cfg.sessions_dir)
    events: queue.Queue = queue.Queue()

    def on_chunk(pcm: bytes):
        text = ear.feed(pcm)
        if text and text.strip():
            events.put(("utt", text))

    mic = MicListener(on_chunk)

    if cfg.hotkeys:
        try:
            import keyboard

            keyboard.add_hotkey("ctrl+alt+j", lambda: events.put(("hot", "toggle")))
            keyboard.add_hotkey("ctrl+alt+s", lambda: events.put(("hot", "solution")))
            keyboard.add_hotkey("ctrl+alt+o", lambda: events.put(("hot", "offtopic" if not sess.offtopic else "ontopic")))
            keyboard.add_hotkey("ctrl+alt+k", lambda: events.put(("hot", "finish")))
            print("хоткеи: Ctrl+Alt+J запись/пауза · +S решение · +O оффтоп · +K конец\n")
        except Exception:
            print("хоткеи недоступны (pip install keyboard)\n")

    print("Аколит на посту. Команды: «Аколит, запись» · «стоп» · «это решение» · «это флуд» · «флуд окончен» · «отмена» · «конец». Ctrl+C — выход.\n")
    mic.start()
    try:
        while True:
            try:
                kind, payload = events.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "utt":
                if verbose:
                    print(f"  слышу: {payload}")
                if voice.is_busy():
                    continue  # это собственный голос Аколита из динамиков
                m = match(payload)
                if m is None:
                    continue
                intent = m[0]
            else:
                intent = payload
            if intent == "toggle":
                intent = "pause" if (sess.recording and not sess.paused) else "start"
            try:
                _dispatch(intent, payload if kind == "utt" else "", sess, obs, voice, cfg, no_summarize)
            except ObsError as e:
                print(f"! OBS: {e}")
                voice.ack("error")
            except Exception as e:
                # Аколит не имеет права умирать посреди встречи
                print(f"! ошибка обработки команды ({type(e).__name__}): {e}")
                voice.ack("error")
            if sess.finished:
                sess = SessionState(cfg.sessions_dir)
                print(f"\nновая сессия: {sess.dir.name}. Скажи «Аколит, запись».\n")
    except KeyboardInterrupt:
        print()
        if sess.recording:
            ans = input("Идёт запись. Завершить с выжимкой? [Y/n] ").strip().lower()
            if ans in ("", "y", "д"):
                _dispatch("finish", "ctrl+c", sess, obs, voice, cfg, no_summarize)
        mic.stop()
        print("Аколит свободен.")
    return 0


def cmd_test_ear(cfg, seconds=0, debug=False) -> int:
    from .ear import Ear
    from .mic import MicListener

    def on_raw(d):
        words = d.get("result") or []
        conf = sum(w.get("conf", 1.0) for w in words) / max(len(words), 1)
        print(f"  raw: {d.get('text', '')!r} conf={conf:.2f}")

    ear = Ear(cfg.vosk_model, on_raw=on_raw if debug else None)
    got: queue.Queue = queue.Queue()

    def on_chunk(pcm: bytes):
        text = ear.feed(pcm)
        if text and text.strip():
            got.put(text)

    mic = MicListener(on_chunk, min_rms=cfg.mic_rms_gate, debug=debug)
    mic.start()
    print("Тест ушей: говори команды в микрофон. Ctrl+C — выход.\n")
    deadline = time.time() + seconds if seconds else None
    try:
        while deadline is None or time.time() < deadline:
            try:
                text = got.get(timeout=0.5)
            except queue.Empty:
                continue
            m = match(text)
            verdict = m[0] if m else "— (не команда)"
            print(f"«{text}» -> {verdict}")
    except KeyboardInterrupt:
        pass
    mic.stop()
    return 0


def cmd_devices(cfg) -> int:
    import sounddevice as sd

    print("Входы:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = " <- по умолчанию" if i == sd.default.device[0] else ""
            print(f"  [{i}] {d['name']} ({d['default_samplerate']} Hz){mark}")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import logging

    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)  # трейсбек при отказе связи только мешает
    ap = argparse.ArgumentParser(prog="acolyte", description="Голосовой писарь для Jitsi-созвонов")
    ap.add_argument("--config", type=Path, default=None, help="путь к acolyte.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="дежурство: слушать команды, писать, выжимать")
    s.add_argument("--verbose", action="store_true", help="печатать все распознанные фразы")
    s.add_argument("--no-summarize", action="store_true", help="не запускать пайплайн после «конец»")

    s = sub.add_parser("test-ear", help="проверка распознавания команд без OBS")
    s.add_argument("--seconds", type=int, default=0, help="0 = до Ctrl+C")
    s.add_argument("--debug", action="store_true", help="показывать уровень сигнала")

    s = sub.add_parser("doctor", help="проверка окружения")
    s.add_argument("--probe", action="store_true", help="пробная 3-сек запись через OBS")

    s = sub.add_parser("transcribe", help="транскрипция готовой сессии")
    s.add_argument("dir", type=Path)

    s = sub.add_parser("summarize", help="выжимка готовой сессии")
    s.add_argument("dir", type=Path)

    s = sub.add_parser("publish", help="публикация выжимки (всегда с явным подтверждением)")
    s.add_argument("dir", type=Path)
    s.add_argument("--confluence", action="store_true")
    s.add_argument("--rag", action="store_true")
    s.add_argument("--yes", action="store_true", help="не спрашивать подтверждение (для скриптов)")

    sub.add_parser("devices", help="список микрофонов")

    a = ap.parse_args(argv)
    cfg = Config.load(a.config)

    if a.cmd == "serve":
        return cmd_serve(cfg, a.verbose, a.no_summarize)
    if a.cmd == "test-ear":
        return cmd_test_ear(cfg, a.seconds, a.debug)
    if a.cmd == "doctor":
        from .doctor import run

        return run(cfg, probe=a.probe)
    if a.cmd == "devices":
        return cmd_devices(cfg)
    if a.cmd == "transcribe":
        from .transcribe import transcribe_session

        out = transcribe_session(a.dir, cfg)
        print(out)
        return 0
    if a.cmd == "summarize":
        from .summarize import summarize_session

        out = summarize_session(a.dir, cfg)
        print(out)
        return 0
    if a.cmd == "publish":
        from .publish import export_rag, publish_confluence

        summary_path = a.dir / "summary.md"
        if not summary_path.exists():
            print(f"! нет {summary_path}; сначала acolyte summarize {a.dir}")
            return 1
        summary = summary_path.read_text(encoding="utf-8")

        targets = [t for t, on in (("confluence", a.confluence), ("rag", a.rag)) if on]
        if not targets:
            ans = input("Куда публиковать? [1] Confluence · [2] RAG · [3] оба · Enter — отмена: ").strip()
            targets = {"1": ["confluence"], "2": ["rag"], "3": ["confluence", "rag"]}.get(ans, [])
            if not targets:
                print("Отменено.")
                return 1

        print("\n--- что уйдёт наружу ---")
        print("\n".join(summary.splitlines()[:12]))
        if len(summary.splitlines()) > 12:
            print("…")
        for t in targets:
            if t == "confluence":
                print(f"Назначение: Confluence {cfg.confluence_url} (space {cfg.confluence_space})")
            else:
                print(f"Назначение: RAG-выгрузка → {cfg.rag_jsonl}")
        print("------------------------\n")

        if not a.yes:
            ok = input(f"Публиковать в {', '.join(targets)}? [y/N] ").strip().lower()
            if ok not in ("y", "yes", "д", "да"):
                print("Отменено.")
                return 1

        if "confluence" in targets:
            print(publish_confluence(a.dir, cfg))
        if "rag" in targets:
            p = export_rag(a.dir, cfg)
            print(f"RAG-выгрузка: {p}")
            print("Дальше проиндексируй своим пайплайном memory-rag (build_index.py).")
        return 0
    return 1
