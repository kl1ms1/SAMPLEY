"""Запись сэмпла с микрофона или линейного входа.

Состояния:
  IDLE      — ничего не пишем, но меряем уровень (индикатор на экране);
  ARMED     — ждём звука: запись начнётся сама, когда громкость перейдёт порог
              (небольшой кусок до порога сохраняется, чтобы не съесть атаку);
  RECORDING — пишем, пока не нажали стоп или не кончилось время;
  DONE      — готово: take() отдаёт обрезанный и нормализованный сэмпл.
"""

from __future__ import annotations

from collections import deque
from enum import Enum

import numpy as np

from .sample import RATE, Sample

PREROLL = int(RATE * 0.03)       # 30 мс до порога
MAX_SECONDS = 30


class RecState(Enum):
    IDLE = "ожидание"
    ARMED = "жду звук"
    RECORDING = "запись"
    DONE = "готово"


class Recorder:
    def __init__(self, threshold: float = 0.05, max_seconds: float = MAX_SECONDS):
        self.threshold = threshold
        self.max_frames = int(max_seconds * RATE)
        self.state = RecState.IDLE
        self.level = 0.0
        self._pre: deque[np.ndarray] = deque()
        self._pre_frames = 0
        self._chunks: list[np.ndarray] = []
        self._frames = 0

    @property
    def seconds(self) -> float:
        return self._frames / RATE

    def arm(self) -> None:
        """Запись начнётся сама, как только будет звук."""
        self._reset()
        self.state = RecState.ARMED

    def start(self) -> None:
        """Писать сразу, без ожидания звука."""
        self._reset()
        self.state = RecState.RECORDING

    def stop(self) -> None:
        if self.state is RecState.RECORDING:
            self.state = RecState.DONE
        elif self.state is RecState.ARMED:
            self.state = RecState.IDLE

    def cancel(self) -> None:
        self._reset()
        self.state = RecState.IDLE

    def _reset(self) -> None:
        self._pre.clear()
        self._pre_frames = 0
        self._chunks = []
        self._frames = 0

    def feed(self, block: np.ndarray) -> None:
        """Вызывается звуковым потоком на каждый блок с входа."""
        block = np.asarray(block, dtype=np.float32)
        if block.ndim == 1:
            block = block[:, None]
        if block.shape[1] == 1:
            block = np.repeat(block, 2, axis=1)
        self.level = float(np.max(np.abs(block))) if len(block) else 0.0
        if self.state is RecState.ARMED:
            loud = np.flatnonzero(np.max(np.abs(block), axis=1) >= self.threshold)
            if loud.size == 0:
                self._pre.append(block.copy())
                self._pre_frames += len(block)
                while self._pre and self._pre_frames - len(self._pre[0]) >= PREROLL:
                    self._pre_frames -= len(self._pre.popleft())
                return
            self.state = RecState.RECORDING
            self._chunks = list(self._pre)
            self._frames = self._pre_frames
            self._pre.clear()
        if self.state is RecState.RECORDING:
            room = self.max_frames - self._frames
            self._chunks.append(block[:room].copy())
            self._frames += min(len(block), room)
            if self._frames >= self.max_frames:
                self.state = RecState.DONE

    def take(self, name: str = "Запись") -> Sample | None:
        if self.state is not RecState.DONE or not self._chunks:
            return None
        data = np.concatenate(self._chunks)
        self.cancel()
        s = Sample(name, data).trimmed(self.threshold / 2)
        return s.normalized(0.9)
