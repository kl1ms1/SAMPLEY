"""Наборы (киты) на карте памяти.

Кит — папка: 16 WAV-файлов (pad01.wav … pad16.wav) + kit.json с настройками
пэдов, темпом и паттернами. Папки можно копировать на компьютер и обратно,
а WAV — заменять своими (имя пэда берётся из kit.json, иначе из имени файла).
"""

from __future__ import annotations

import json
import os

from .engine import Engine, Mode, Pad
from .kit_synth import default_kit
from .sample import load_wav, save_wav
from .sequencer import PADS, Pattern

KITS_DIR = os.path.expanduser(os.environ.get("SAMPLEY_KITS", "~/sampley/kits"))


def list_kits(root: str = KITS_DIR) -> list[str]:
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "kit.json")))


def save_kit(engine: Engine, name: str, root: str = KITS_DIR) -> str:
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    pads = []
    for i, p in enumerate(engine.pads):
        wav = f"pad{i + 1:02d}.wav"
        if p.sample is not None:
            save_wav(p.sample, os.path.join(path, wav))
        elif os.path.exists(os.path.join(path, wav)):
            os.remove(os.path.join(path, wav))
        pads.append({"file": wav if p.sample else None, "name": p.name, "volume": p.volume,
                     "pitch": p.pitch, "pan": p.pan, "start": p.start, "end": p.end,
                     "mode": p.mode.name, "choke": p.choke, "reverse": p.reverse})
    meta = {"version": 1, "bpm": engine.seq.bpm, "swing": engine.seq.swing, "master": engine.master,
            "pads": pads,
            "patterns": [[[s for s, on in enumerate(row) if on] for row in pat.grid]
                         for pat in engine.seq.patterns]}
    tmp = os.path.join(path, "kit.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(path, "kit.json"))       # не побьётся, если сядет батарея
    return path


def load_kit(engine: Engine, name: str, root: str = KITS_DIR) -> None:
    path = os.path.join(root, name)
    with open(os.path.join(path, "kit.json"), encoding="utf-8") as f:
        meta = json.load(f)
    engine.stop_all()
    for i in range(PADS):
        d = meta["pads"][i] if i < len(meta.get("pads", [])) else {}
        sample = None
        if d.get("file") and os.path.exists(os.path.join(path, d["file"])):
            sample = load_wav(os.path.join(path, d["file"]), d.get("name"))
        engine.pads[i] = Pad(sample=sample, volume=d.get("volume", 0.8), pitch=d.get("pitch", 0.0),
                             pan=d.get("pan", 0.0), start=d.get("start", 0.0), end=d.get("end", 1.0),
                             mode=Mode[d.get("mode", "ONESHOT")], choke=d.get("choke", 0),
                             reverse=d.get("reverse", False))
    engine.seq.bpm = meta.get("bpm", 120)
    engine.seq.swing = meta.get("swing", 0.0)
    engine.master = meta.get("master", 0.8)
    for pat, rows in zip(engine.seq.patterns, meta.get("patterns", [])):
        pat.grid = [[s in set(r) for s in range(pat.steps)] for r in rows] + \
                   [[False] * pat.steps for _ in range(PADS - len(rows))]


def load_default(engine: Engine) -> None:
    """Встроенный синтезированный кит + демо-бит в первом паттерне."""
    for pad, s in zip(engine.pads, default_kit()):
        pad.sample = s
    engine.pads[2].choke = engine.pads[3].choke = 1       # хэты глушат друг друга
    for i in range(8, 14):
        engine.pads[i].mode = Mode.GATE                   # бас и аккорды — пока держишь
    demo = Pattern()
    for s in (0, 6, 8, 11):
        demo.grid[0][s] = True
    for s in (4, 12):
        demo.grid[1][s] = True
    for s in range(0, 16, 2):
        demo.grid[2][s] = True
    demo.grid[3][14] = True
    demo.grid[8][0] = demo.grid[9][6] = demo.grid[10][10] = True
    engine.seq.patterns[0] = demo
