"""Разовая загрузка модели Vosk для распознавания команд. Только stdlib."""

import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"

root = Path(__file__).parent / "models"
target = root / "vosk-model-small-ru-0.22"
if target.exists():
    print(f"уже есть: {target}")
    sys.exit(0)

root.mkdir(exist_ok=True)
zip_path = root / "vosk-model-small-ru-0.22.zip"
print(f"качаю {URL} (~45 МБ)…")
with urllib.request.urlopen(URL) as r, open(zip_path, "wb") as f:
    while chunk := r.read(1 << 20):
        f.write(chunk)
with zipfile.ZipFile(zip_path) as z:
    z.extractall(root)
zip_path.unlink()
print(f"готово: {target}")
