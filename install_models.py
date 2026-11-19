"""Разовая загрузка модели Vosk для распознавания команд. Только stdlib.

Системный прокси подхватывается сам (urllib читает WinINET/ env)."""

import socket
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
ATTEMPTS = 3
socket.setdefaulttimeout(60)

root = Path(__file__).parent / "models"
target = root / "vosk-model-small-ru-0.22"
if target.exists():
    print(f"уже есть: {target}")
    sys.exit(0)

root.mkdir(exist_ok=True)
zip_path = root / "vosk-model-small-ru-0.22.zip"

for attempt in range(1, ATTEMPTS + 1):
    try:
        print(f"попытка {attempt}: качаю {URL} (~45 МБ)…")
        with urllib.request.urlopen(URL, timeout=60) as r, open(zip_path, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                print(f"\r  {zip_path.stat().st_size / 1e6:.1f} МБ", end="", flush=True)
        print()
        break
    except Exception as e:
        print(f"\n  ошибка: {e}")
        zip_path.unlink(missing_ok=True)
        if attempt == ATTEMPTS:
            print("не получилось; проверь прокси/сеть или скачай архив руками в models/")
            sys.exit(1)
        time.sleep(3)

with zipfile.ZipFile(zip_path) as z:
    z.extractall(root)
zip_path.unlink()
print(f"готово: {target}")
