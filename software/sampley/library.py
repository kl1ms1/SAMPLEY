"""Библиотека звуков на карте: всё, что записал, и всё, что закинул WAV-ами.

Записи сохраняются сами в ~/sampley/samples/rec-ГГГГММДД-ЧЧММСС.wav —
ничего не теряется, даже если потом перезаписал пэд. Сюда же можно
копировать свои WAV с компьютера (можно по папкам).
"""

from __future__ import annotations

import os
import time

from .sample import Sample, save_wav

SAMPLES_DIR = os.path.expanduser(os.environ.get("SAMPLEY_SAMPLES", "~/sampley/samples"))


def list_samples(root: str = SAMPLES_DIR) -> list[str]:
    """Пути WAV относительно root, сначала свежие записи."""
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".wav"):
                full = os.path.join(dirpath, f)
                found.append((os.path.getmtime(full), os.path.relpath(full, root)))
    return [p for _, p in sorted(found, reverse=True)]


def save_recording(sample: Sample, root: str = SAMPLES_DIR) -> str:
    os.makedirs(root, exist_ok=True)
    name = time.strftime("rec-%Y%m%d-%H%M%S")
    path, n = os.path.join(root, name + ".wav"), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(root, f"{name}-{n}.wav")
    save_wav(sample, path)
    return path
