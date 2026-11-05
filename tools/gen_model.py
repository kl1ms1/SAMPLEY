#!/usr/bin/env python3
"""Собирает docs/model/sampley-model.html: шаблон + настоящие экраны SAMPLEY.

    python3 tools/gen_model.py      (после python3 -m sampley --demo, чтобы обновить картинки)
"""
import base64
import io
import json
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
screens = {}
for n in ["play", "chop", "step", "sample", "bank_b"]:
    im = Image.open(os.path.join(ROOT, "docs", "img", f"screen_{n}.png")).convert("RGB")
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    screens[n] = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
tpl = open(os.path.join(HERE, "model_template.html"), encoding="utf-8").read()
out = os.path.join(ROOT, "docs", "model", "sampley-model.html")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(tpl.replace("__SCREENS__", json.dumps(screens)))
print(f"→ {os.path.relpath(out)}")
