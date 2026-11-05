"""Звук в памяти: загрузка/сохранение WAV, обрезка, нормализация.

Внутри всё хранится как numpy float32 формы (кадры, 2) — стерео, −1…+1,
на частоте движка (44.1 кГц). Моно-файлы раздваиваются, файлы с другой
частотой пересчитываются при загрузке, чтобы в звуковом потоке не тратить
на это процессор Pi Zero.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass

import numpy as np

RATE = 44100


@dataclass
class Sample:
    name: str
    data: np.ndarray            # float32 (n, 2)

    @property
    def frames(self) -> int:
        return len(self.data)

    @property
    def seconds(self) -> float:
        return self.frames / RATE

    @classmethod
    def from_mono(cls, name: str, mono: np.ndarray) -> "Sample":
        mono = np.asarray(mono, dtype=np.float32)
        return cls(name, np.repeat(mono[:, None], 2, axis=1))

    def peak(self) -> float:
        return float(np.max(np.abs(self.data))) if self.frames else 0.0

    def normalized(self, target: float = 0.9) -> "Sample":
        p = self.peak()
        if p < 1e-6:
            return self
        return Sample(self.name, (self.data * (target / p)).astype(np.float32))

    def trimmed(self, threshold: float = 0.02, pad_ms: float = 5.0) -> "Sample":
        """Отрезать тишину в начале и в конце (то, что тише threshold)."""
        loud = np.flatnonzero(np.max(np.abs(self.data), axis=1) >= threshold)
        if loud.size == 0:
            return self
        pad = int(RATE * pad_ms / 1000)
        a = max(0, loud[0] - pad)
        b = min(self.frames, loud[-1] + pad + 1)
        return Sample(self.name, self.data[a:b].copy())

    def reversed(self) -> "Sample":
        return Sample(self.name, self.data[::-1].copy())

    def overview(self, width: int) -> np.ndarray:
        """Пики для рисования волны: массив длины width, 0…1."""
        if self.frames == 0 or width <= 0:
            return np.zeros(max(width, 0), dtype=np.float32)
        mono = np.max(np.abs(self.data), axis=1)
        edges = np.linspace(0, self.frames, width + 1).astype(int)
        return np.array([mono[a:max(b, a + 1)].max() if a < self.frames else 0.0
                         for a, b in zip(edges[:-1], edges[1:])], dtype=np.float32)


def resample(data: np.ndarray, src_rate: int, dst_rate: int = RATE) -> np.ndarray:
    """Линейный пересчёт частоты. Для сэмплера на Pi Zero этого достаточно."""
    if src_rate == dst_rate or len(data) == 0:
        return data
    n = max(1, round(len(data) * dst_rate / src_rate))
    x = np.linspace(0, len(data) - 1, n)
    return np.stack([np.interp(x, np.arange(len(data)), data[:, c]) for c in range(data.shape[1])],
                    axis=1).astype(np.float32)


def load_wav(path: str, name: str | None = None) -> Sample:
    """WAV 8/16/24/32 бит, моно или стерео, любая частота."""
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        i = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        i = np.where(i & 0x800000, i - 0x1000000, i)
        a = i.astype(np.float32) / 8388608
    elif width == 4:
        a = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"{path}: неподдерживаемая разрядность {width * 8} бит")
    a = a.reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, axis=1)
    elif ch > 2:
        a = a[:, :2]
    if name is None:
        import os
        name = os.path.splitext(os.path.basename(path))[0]
    return Sample(name, resample(a.astype(np.float32), rate))


def save_wav(sample: Sample, path: str) -> None:
    """Сохранить 16 бит / 44.1 кГц / стерео."""
    pcm = (np.clip(sample.data, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
