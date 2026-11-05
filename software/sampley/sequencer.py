"""Секвенсор: 16 шагов × 64 пэда (4 банка по 16), 8 паттернов, свинг, запись «вживую».

Время считается в кадрах звука, а не по часам: секвенсор двигает движок
прямо внутри звукового потока, поэтому удары ложатся точно в долю
(до одного кадра — 0.02 мс), даже если интерфейс в этот момент тормозит.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .sample import RATE

STEPS = 16
BANK_SIZE = 16
BANKS = 4
PADS = BANK_SIZE * BANKS          # банки A–D по 16 пэдов
PATTERNS = 8


@dataclass
class Pattern:
    steps: int = STEPS
    grid: list[list[bool]] = field(default_factory=lambda: [[False] * STEPS for _ in range(PADS)])

    def toggle(self, pad: int, step: int) -> bool:
        self.grid[pad][step] = not self.grid[pad][step]
        return self.grid[pad][step]

    def hits(self, step: int) -> list[int]:
        return [p for p in range(PADS) if self.grid[p][step]]

    def clear(self, pad: int | None = None) -> None:
        for p in range(PADS) if pad is None else [pad]:
            self.grid[p] = [False] * self.steps

    def is_empty(self) -> bool:
        return not any(any(row) for row in self.grid)


class Sequencer:
    def __init__(self, bpm: float = 120.0):
        self.patterns = [Pattern() for _ in range(PATTERNS)]
        self.current = 0
        self.queued: int | None = None      # следующий паттерн — переключится в начале такта
        self.bpm = bpm
        self.swing = 0.0                    # 0…0.6: насколько опаздывают чётные шестнадцатые
        self.playing = False
        self.recording = False              # запись ударов в паттерн во время игры
        self.step = 0                       # шаг, который прозвучал последним
        self._next_step = 0
        self._until_next = 0.0              # кадров до следующего шага
        self._skip: set[tuple[int, int]] = set()  # (пэд, шаг): уже сыгран вживую, не повторять

    @property
    def pattern(self) -> Pattern:
        return self.patterns[self.current]

    def frames_per_step(self) -> float:
        return RATE * 60.0 / self.bpm / 4      # шаг = шестнадцатая

    def _step_len(self, step: int) -> float:
        """Длина шага с учётом свинга: нечётный (0,2,…) длиннее, чётный короче."""
        f = self.frames_per_step()
        return f * (1 + self.swing) if step % 2 == 0 else f * (1 - self.swing)

    def start(self) -> None:
        self.playing = True
        self._next_step = 0
        self._until_next = 0.0

    def stop(self) -> None:
        self.playing = False
        self.recording = False

    def toggle(self) -> bool:
        self.stop() if self.playing else self.start()
        return self.playing

    def advance(self, frames: int) -> list[tuple[int, int]]:
        """Сдвинуть время на frames кадров. Вернуть [(смещение в блоке, пэд)]."""
        if not self.playing:
            return []
        events: list[tuple[int, int]] = []
        pos = self._until_next
        while pos < frames:
            step = self._next_step
            if step == 0 and self.queued is not None:
                self.current, self.queued = self.queued, None
            self.step = step
            events += [(int(pos), p) for p in self.pattern.hits(step) if (p, step) not in self._skip]
            self._skip = {k for k in self._skip if k[1] != step}
            pos += self._step_len(step)
            self._next_step = (step + 1) % self.pattern.steps
        self._until_next = pos - frames
        return events

    def record_hit(self, pad: int) -> int | None:
        """Удар пэда во время записи: ставим на ближайший шаг (квантизация)."""
        if not (self.playing and self.recording):
            return None
        # Мы между self.step и _next_step. Если до следующего шага меньше половины —
        # ставим на следующий; сам удар уже прозвучал вживую, поэтому
        # на этом проходе секвенсор его не повторяет.
        if self._until_next < self._step_len(self.step) / 2:
            step = self._next_step
            self._skip.add((pad, step))
        else:
            step = self.step
        self.pattern.grid[pad][step] = True
        return step
