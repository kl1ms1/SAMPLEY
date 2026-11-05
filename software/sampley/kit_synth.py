"""Стартовый набор звуков, синтезированный кодом.

Чтобы сэмплер играл «из коробки» без чужих (и чьих-то авторских) сэмплов:
бочка, малый, хэты, хлопок, томы, бас, аккорды, «бип». Свои звуки потом
записываются с микрофона / линейного входа или кидаются на карту WAV-файлами.
"""

from __future__ import annotations

import numpy as np

from .sample import RATE, Sample

_rng = np.random.default_rng(7)


def _t(sec: float) -> np.ndarray:
    return np.arange(int(RATE * sec), dtype=np.float32) / RATE


def _env(t: np.ndarray, decay: float, attack: float = 0.001) -> np.ndarray:
    a = np.clip(t / attack, 0, 1)
    return a * np.exp(-t / decay)


def _noise(n: int) -> np.ndarray:
    return _rng.uniform(-1, 1, n).astype(np.float32)


def _hp(x: np.ndarray, k: float = 0.85) -> np.ndarray:
    """Простейший фильтр верхних частот (убирает «бубнёж» у шума)."""
    y = np.empty_like(x)
    prev_x = prev_y = 0.0
    for i, v in enumerate(x):
        prev_y = k * (prev_y + v - prev_x)
        prev_x = v
        y[i] = prev_y
    return y


def kick() -> np.ndarray:
    t = _t(0.5)
    freq = 45 + 110 * np.exp(-t / 0.04)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    click = _noise(len(t)) * _env(t, 0.002) * 0.3
    return np.tanh(1.6 * np.sin(phase) * _env(t, 0.18)) + click


def snare() -> np.ndarray:
    t = _t(0.35)
    body = np.sin(2 * np.pi * 190 * t) * _env(t, 0.05)
    return 0.5 * body + 0.7 * _hp(_noise(len(t))) * _env(t, 0.09)


def hat(open_: bool) -> np.ndarray:
    t = _t(0.5 if open_ else 0.08)
    metal = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in (205, 304, 369, 522, 540, 800))
    x = _hp(0.15 * metal + _noise(len(t)), 0.6)
    return 0.6 * x * _env(t, 0.18 if open_ else 0.02)


def clap() -> np.ndarray:
    t = _t(0.3)
    e = sum(_env(np.clip(t - d, 0, None), 0.008) * (t >= d) for d in (0, 0.011, 0.023))
    e = e + _env(np.clip(t - 0.03, 0, None), 0.07) * (t >= 0.03)
    return 0.6 * _hp(_noise(len(t)), 0.7) * e


def tom(f0: float) -> np.ndarray:
    t = _t(0.45)
    freq = f0 * (1 + 0.5 * np.exp(-t / 0.03))
    return np.sin(2 * np.pi * np.cumsum(freq) / RATE) * _env(t, 0.16)


def bass(note: int) -> np.ndarray:
    t = _t(0.6)
    f = 440 * 2 ** ((note - 69) / 12)
    saw = 2 * ((f * t) % 1) - 1
    return 0.5 * np.tanh(2 * saw * _env(t, 0.25, 0.003))


def chord(notes: tuple[int, ...]) -> np.ndarray:
    t = _t(1.2)
    x = sum(np.sin(2 * np.pi * 440 * 2 ** ((n - 69) / 12) * t) +
            0.3 * np.sin(4 * np.pi * 440 * 2 ** ((n - 69) / 12) * t) for n in notes)
    return 0.35 * x / len(notes) * _env(t, 0.5, 0.01)


def blip() -> np.ndarray:
    t = _t(0.15)
    return 0.5 * np.sign(np.sin(2 * np.pi * 1320 * t)) * _env(t, 0.04)


def zap() -> np.ndarray:
    t = _t(0.3)
    freq = 2000 * np.exp(-t / 0.05) + 80
    return 0.6 * np.sin(2 * np.pi * np.cumsum(freq) / RATE) * _env(t, 0.1)


def default_kit() -> list[Sample]:
    """16 звуков — по одному на пэд (сверху вниз, слева направо)."""
    sounds = [
        ("Бочка", kick()), ("Малый", snare()), ("Хэт закр", hat(False)), ("Хэт откр", hat(True)),
        ("Хлопок", clap()), ("Том выс", tom(220)), ("Том ср", tom(160)), ("Том низ", tom(110)),
        ("Бас C", bass(36)), ("Бас D#", bass(39)), ("Бас F", bass(41)), ("Бас G", bass(43)),
        ("Аккорд 1", chord((60, 63, 67))), ("Аккорд 2", chord((58, 62, 65))), ("Бип", blip()), ("Зап", zap()),
    ]
    out = []
    for name, x in sounds:
        x = np.asarray(x, dtype=np.float32)
        out.append(Sample.from_mono(name, x).normalized(0.8))
    return out
