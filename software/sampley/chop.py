"""CHOP — нарезка длинной записи по пэдам.

Записал кусок улицы, песни, разговора → режешь на срезы → каждый срез
ложится на свой пэд текущего банка. Два способа:
  АВТО  — по ударам (резкий рост громкости), чувствительность крутится;
  РОВНО — на N одинаковых кусков (для лупов в темп).
Каждый срез потом можно подвинуть: начало и конец.
Все пэды ссылаются на один и тот же звук в памяти (разные start/end),
поэтому нарезка не тратит память.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .engine import Engine, Mode
from .sample import RATE, Sample
from .sequencer import BANK_SIZE

HOP = 256                         # окно анализа ≈ 6 мс
MIN_GAP = int(RATE * 0.06)        # срезы не ближе 60 мс


class ChopMode(Enum):
    AUTO = "Авто"
    EQUAL = "Ровно"


def _flux(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Насколько (в логарифме) громкость окна выросла над минимумом трёх предыдущих."""
    n = len(x) // HOP
    e = np.sqrt((x[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1)) + 1e-9
    le = np.log(e)
    prev = np.array([le[max(0, i - 3):i].min() if i else le[0] for i in range(n)])
    return np.maximum(0.0, le - prev), e


def onsets(sample: Sample, sensitivity: float = 0.5, limit: int = BANK_SIZE) -> list[int]:
    """Начала ударов, в кадрах. sensitivity 0…1: больше — больше срезов.

    Смотрим рост громкости в двух полосах: весь сигнал (бочка, томы, бас)
    и «верха» (малый, хлопки, тарелки, согласные в голосе). Удар — пик
    роста выше порога. Так находятся и удары на хвосте предыдущих.
    """
    x = sample.data.mean(axis=1)
    if len(x) < HOP * 4:
        return [0]
    f_all, e_all = _flux(x)
    f_hi, _ = _flux(np.diff(x, prepend=x[0]))
    f = np.maximum(f_all, f_hi)
    loud = e_all > e_all.max() * 0.05
    need = 2.2 - 1.8 * float(np.clip(sensitivity, 0, 1))
    n = len(f)
    cand = [i for i in range(1, n - 1)
            if f[i] > need and loud[i] and f[i] >= f[i - 1] and f[i] > f[i + 1]]
    picked: list[int] = [0]
    for i in sorted(cand, key=lambda i: -f[i]):                 # сначала самые явные
        fr = (i - 1) * HOP                                     # на окно раньше — не съесть атаку
        if all(abs(fr - p) >= MIN_GAP for p in picked):
            picked.append(fr)
        if len(picked) >= limit:
            break
    return sorted(picked)


def equal(sample: Sample, count: int) -> list[int]:
    count = max(1, min(BANK_SIZE, count))
    return [int(sample.frames * i / count) for i in range(count)]


@dataclass
class Chopper:
    sample: Sample
    mode: ChopMode = ChopMode.AUTO
    sensitivity: float = 0.5
    count: int = 8
    cursor: int = 0
    slices: list[list[int]] = field(default_factory=list)     # [начало, конец] в кадрах

    def __post_init__(self):
        if not self.slices:
            self.recut()

    def recut(self) -> None:
        starts = onsets(self.sample, self.sensitivity) if self.mode is ChopMode.AUTO \
            else equal(self.sample, self.count)
        ends = starts[1:] + [self.sample.frames]
        self.slices = [[a, b] for a, b in zip(starts, ends)]
        self.cursor = min(self.cursor, len(self.slices) - 1)

    def toggle_mode(self) -> None:
        self.mode = ChopMode.EQUAL if self.mode is ChopMode.AUTO else ChopMode.AUTO
        self.recut()

    def amount(self, clicks: int) -> None:
        """K1: в АВТО — чувствительность, в РОВНО — сколько кусков."""
        if self.mode is ChopMode.AUTO:
            self.sensitivity = round(float(np.clip(self.sensitivity + clicks * 0.05, 0, 1)), 2)
        else:
            self.count = max(1, min(BANK_SIZE, self.count + clicks))
        self.recut()

    def nudge(self, edge: int, clicks: int) -> None:
        """Сдвинуть начало (edge=0) или конец (edge=1) текущего среза, шаг 5 мс."""
        s = self.slices[self.cursor]
        step = int(RATE * 0.005) * clicks
        if edge == 0:
            s[0] = int(np.clip(s[0] + step, 0, s[1] - HOP))
        else:
            s[1] = int(np.clip(s[1] + step, s[0] + HOP, self.sample.frames))

    def select(self, clicks: int) -> None:
        self.cursor = (self.cursor + clicks) % len(self.slices)

    def apply(self, engine: Engine, first_pad: int) -> int:
        """Разложить срезы по пэдам начиная с first_pad. Вернуть сколько легло."""
        n = self.sample.frames
        placed = 0
        for i, (a, b) in enumerate(self.slices[:BANK_SIZE]):
            pad_i = first_pad + i
            if pad_i >= len(engine.pads):
                break
            p = engine.pads[pad_i]
            p.sample, p.start, p.end = self.sample, a / n, b / n
            p.label = f"{self.sample.name[:7].rstrip()}·{i + 1}"
            p.mode, p.reverse, p.pitch, p.mute = Mode.ONESHOT, False, 0.0, False
            placed += 1
        return placed
