"""Звуковой движок: 16 пэдов, полифония, тон, панорама, режимы, группы глушения.

Работает внутри звукового потока (callback sounddevice / ALSA). Интерфейс
и кнопки в поток не лезут — они кладут команды в очередь, движок забирает
их в начале каждого блока. Поэтому медленный экран не рвёт звук.

Режимы пэда:
  ONESHOT — нажал, звук играет до конца (барабаны);
  GATE    — играет, пока держишь (бас, аккорды);
  LOOP    — играет по кругу, пока держишь;
  TOGGLE  — нажал — пошёл луп, нажал ещё — остановился.
Группа глушения (choke): пэды с одной группой обрывают друг друга —
закрытый хэт глушит открытый, как на настоящей тарелке.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .recorder import Recorder
from .sample import RATE, Sample
from .sequencer import PADS, Sequencer

FADE = int(RATE * 0.004)          # 4 мс: мягкий хвост, чтобы не щёлкало при обрыве


class Mode(Enum):
    ONESHOT = "Удар"
    GATE = "Держать"
    LOOP = "Луп"
    TOGGLE = "Луп вкл/выкл"


@dataclass
class Pad:
    sample: Sample | None = None
    volume: float = 0.8             # 0…1
    pitch: float = 0.0              # полутоны, −24…+24
    pan: float = 0.0                # −1 (лево)…+1 (право)
    start: float = 0.0              # доля длины, 0…1
    end: float = 1.0
    mode: Mode = Mode.ONESHOT
    choke: int = 0                  # 0 — без группы
    reverse: bool = False
    mute: bool = False

    @property
    def name(self) -> str:
        return self.sample.name if self.sample else "—"

    def gains(self) -> tuple[float, float]:
        # «равномощная» панорама: в центре оба канала −3 дБ
        a = (self.pan + 1) * np.pi / 4
        return self.volume * float(np.cos(a)) * 1.414, self.volume * float(np.sin(a)) * 1.414


@dataclass
class Voice:
    pad: int
    data: np.ndarray
    pos: float
    end: float
    rate: float
    gl: float
    gr: float
    loop_start: float
    loop: bool
    born: int
    releasing: int = -1             # >=0 — сколько кадров хвоста осталось
    fade_in: int = FADE


@dataclass
class Engine:
    max_voices: int = 16
    block: int = 256
    pads: list[Pad] = field(default_factory=lambda: [Pad() for _ in range(PADS)])
    master: float = 0.8
    seq: Sequencer = field(default_factory=Sequencer)
    recorder: Recorder = field(default_factory=Recorder)

    def __post_init__(self):
        self.voices: list[Voice] = []
        self._cmds: queue.SimpleQueue = queue.SimpleQueue()
        self._clock = 0
        self.playing_pads: set[int] = set()        # для подсветки пэдов и экрана
        self.level = 0.0                           # пик выхода последнего блока

    # --- команды из интерфейса (любой поток) --------------------------------
    def note_on(self, pad: int, velocity: float = 1.0) -> None:
        self._cmds.put(("on", pad, velocity))

    def note_off(self, pad: int) -> None:
        self._cmds.put(("off", pad, 0.0))

    def stop_all(self) -> None:
        self._cmds.put(("panic", 0, 0.0))

    # --- внутри звукового потока -------------------------------------------
    def _start_voice(self, pad_i: int, velocity: float, offset: int = 0) -> None:
        pad = self.pads[pad_i]
        if pad.sample is None or pad.mute or pad.sample.frames < 2:
            return
        if pad.mode is Mode.TOGGLE and any(v.pad == pad_i and v.releasing < 0 for v in self.voices):
            self._release(pad_i)
            return
        if pad.choke:
            for v in self.voices:
                if v.releasing < 0 and self.pads[v.pad].choke == pad.choke:
                    v.releasing = FADE
        # повторный удар того же пэда в режиме ONESHOT обрывает прошлый
        for v in self.voices:
            if v.pad == pad_i and v.releasing < 0:
                v.releasing = FADE
        if len(self.voices) >= self.max_voices:
            oldest = min(self.voices, key=lambda v: (v.releasing < 0, v.born))
            self.voices.remove(oldest)
        data = pad.sample.data[::-1] if pad.reverse else pad.sample.data
        n = len(data)
        a = int(min(pad.start, pad.end) * (n - 1))
        b = max(a + 2, int(max(pad.start, pad.end) * n))
        gl, gr = pad.gains()
        self.voices.append(Voice(
            pad=pad_i, data=data, pos=float(a) - offset * 2 ** (pad.pitch / 12), end=float(b),
            rate=2 ** (pad.pitch / 12), gl=gl * velocity, gr=gr * velocity, loop_start=float(a),
            loop=pad.mode in (Mode.LOOP, Mode.TOGGLE), born=self._clock + offset,
            fade_in=FADE if a > 0 else 0,       # с самого начала — без подъёма, чтобы бочка «щёлкала»
        ))

    def _release(self, pad_i: int) -> None:
        for v in self.voices:
            if v.pad == pad_i and v.releasing < 0:
                v.releasing = FADE

    def _handle(self, cmd: str, pad: int, vel: float) -> None:
        if cmd == "on":
            self._start_voice(pad, vel)
            self.seq.record_hit(pad)
        elif cmd == "off":
            if self.pads[pad].mode in (Mode.GATE, Mode.LOOP):
                self._release(pad)
        elif cmd == "panic":
            for v in self.voices:
                v.releasing = FADE

    def _render_voice(self, v: Voice, out: np.ndarray, a: int, b: int) -> bool:
        """Подмешать голос в out[a:b]. Вернуть False, если голос закончился."""
        n = b - a
        idx = v.pos + np.arange(n, dtype=np.float64) * v.rate
        skip = int(np.count_nonzero(idx < v.loop_start))   # голос стартует позже начала блока
        if skip >= n:
            v.pos += n * v.rate
            return True
        if v.loop:
            span = v.end - v.loop_start
            idx = np.where(idx >= v.loop_start, v.loop_start + (idx - v.loop_start) % span, idx)
            alive = n
        else:
            alive = int(np.searchsorted(idx, v.end - 1))
        i0 = idx[skip:alive]
        if len(i0) == 0:
            return False
        base = np.floor(i0).astype(np.int64)
        frac = (i0 - base)[:, None].astype(np.float32)
        nxt = np.minimum(base + 1, len(v.data) - 1)
        chunk = v.data[base] * (1 - frac) + v.data[nxt] * frac
        env = np.ones(len(chunk), dtype=np.float32)
        if v.fade_in > 0:                                 # без щелчка, если старт не с нуля
            k = min(v.fade_in, len(env))
            env[:k] = np.linspace(1 - v.fade_in / FADE, 1 - (v.fade_in - k) / FADE, k, dtype=np.float32)
            v.fade_in -= k
        done = False
        if v.releasing >= 0:
            k = min(v.releasing, len(env))
            env[:k] *= np.linspace(v.releasing / FADE, (v.releasing - k) / FADE, k, dtype=np.float32)
            env[k:] = 0
            v.releasing -= k
            done = v.releasing <= 0
        chunk *= env[:, None]
        out[a + skip:a + alive, 0] += chunk[:, 0] * v.gl
        out[a + skip:a + alive, 1] += chunk[:, 1] * v.gr
        v.pos += n * v.rate
        return not done and (v.loop or alive == n)

    def render(self, frames: int, mic: np.ndarray | None = None) -> np.ndarray:
        """Следующий блок звука (frames, 2) float32. mic — блок с входа (для записи)."""
        while True:
            try:
                self._handle(*self._cmds.get_nowait())
            except queue.Empty:
                break
        if mic is not None:
            self.recorder.feed(mic)
        out = np.zeros((frames, 2), dtype=np.float32)
        # удары секвенсора — с точностью до кадра: режем блок на куски
        cuts = self.seq.advance(frames)
        bounds = sorted({0, frames, *(o for o, _ in cuts)})
        for a, b in zip(bounds[:-1], bounds[1:]):
            for off, pad in cuts:
                if off == a:
                    self._start_voice(pad, 1.0)
            self.voices = [v for v in self.voices if self._render_voice(v, out, a, b)]
        self._clock += frames
        out *= self.master
        np.tanh(out, out=out)                     # мягкий ограничитель вместо хрипа
        self.level = float(np.max(np.abs(out))) if frames else 0.0
        self.playing_pads = {v.pad for v in self.voices if v.releasing < 0}
        return out
