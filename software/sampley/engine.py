"""Звуковой движок: 64 пэда (4 банка), полифония, тон, панорама, режимы,
группы глушения, NOTE REPEAT, общий тон и DJ-фильтр с фейдера.

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

try:                                    # фильтр фейдера; без scipy фейдер просто не фильтрует
    from scipy.signal import butter, lfilter
except ImportError:                     # pragma: no cover
    butter = None

FADE = int(RATE * 0.004)          # 4 мс: мягкий хвост, чтобы не щёлкало при обрыве
REPEAT_RATES = {"1/8": 2, "1/16": 4, "1/32": 8, "1/16т": 6}     # ударов на долю


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
    label: str | None = None        # своя подпись (срезы CHOP: «Улица·3»)

    @property
    def name(self) -> str:
        if self.sample is None:
            return "—"
        return self.label or self.sample.name

    def gains(self) -> tuple[float, float]:
        # «равномощная» панорама: в центре оба канала −3 дБ
        a = (self.pan + 1) * np.pi / 4
        return self.volume * float(np.cos(a)) * 1.414, self.volume * float(np.sin(a)) * 1.414


@dataclass
class Voice:
    pad: int
    key: object                     # чем голос глушится/отпускается (пэд или (пэд, ступень))
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
    pads: list[Pad] = field(default_factory=lambda: [Pad() for _ in range(PADS + 1)])  # +1 — прослушка
    master: float = 0.8
    seq: Sequencer = field(default_factory=Sequencer)
    recorder: Recorder = field(default_factory=Recorder)

    def __post_init__(self):
        self.voices: list[Voice] = []
        self._cmds: queue.SimpleQueue = queue.SimpleQueue()
        self._clock = 0
        self.playing_pads: set[int] = set()        # для подсветки пэдов и экрана
        self.level = 0.0                           # пик выхода последнего блока
        self.tune = 0.0                            # общий тон с фейдера, полутоны
        self.filter = 0.0                          # −1 (низы) … 0 (выкл) … +1 (верхи)
        self._filt_key = None
        self._filt = None
        self.repeat_rate = "1/16"
        self._repeat: dict[object, tuple[int, float, float]] = {}   # key → (пэд, сила, тон)
        self._repeat_until = 0.0

    # --- команды из интерфейса (любой поток) --------------------------------
    def note_on(self, pad: int, velocity: float = 1.0, semis: float = 0.0, key=None) -> None:
        """semis — сдвиг тона для этого удара (16 LEVELS), key — своя «клавиша» голоса."""
        self._cmds.put(("on", pad, velocity, semis, pad if key is None else key))

    def note_off(self, pad: int, key=None) -> None:
        self._cmds.put(("off", pad, 0.0, 0.0, pad if key is None else key))

    def repeat_on(self, pad: int, velocity: float = 1.0, semis: float = 0.0, key=None) -> None:
        """NOTE REPEAT: пэд стучит сам с темпом, пока не придёт repeat_off."""
        self._cmds.put(("rep_on", pad, velocity, semis, pad if key is None else key))

    def repeat_off(self, key) -> None:
        self._cmds.put(("rep_off", 0, 0.0, 0.0, key))

    def stop_all(self) -> None:
        self._cmds.put(("panic", 0, 0.0, 0.0, None))

    # --- внутри звукового потока -------------------------------------------
    def _start_voice(self, pad_i: int, velocity: float, semis: float = 0.0, key=None) -> None:
        key = pad_i if key is None else key
        pad = self.pads[pad_i]
        if pad.sample is None or pad.mute or pad.sample.frames < 2:
            return
        if pad.mode is Mode.TOGGLE and any(v.key == key and v.releasing < 0 for v in self.voices):
            self._release(key)
            return
        if pad.choke:
            for v in self.voices:
                if v.releasing < 0 and self.pads[v.pad].choke == pad.choke:
                    v.releasing = FADE
        # повторный удар той же «клавиши» обрывает прошлый (как на MPC)
        self._release(key)
        if len(self.voices) >= self.max_voices:
            oldest = min(self.voices, key=lambda v: (v.releasing < 0, v.born))
            self.voices.remove(oldest)
        data = pad.sample.data[::-1] if pad.reverse else pad.sample.data
        n = len(data)
        a = int(min(pad.start, pad.end) * (n - 1))
        b = max(a + 2, int(max(pad.start, pad.end) * n))
        gl, gr = pad.gains()
        self.voices.append(Voice(
            pad=pad_i, key=key, data=data, pos=float(a), end=float(b),
            rate=2 ** ((pad.pitch + semis) / 12), gl=gl * velocity, gr=gr * velocity, loop_start=float(a),
            loop=pad.mode in (Mode.LOOP, Mode.TOGGLE), born=self._clock,
            fade_in=FADE if a > 0 else 0,       # с самого начала — без подъёма, чтобы бочка «щёлкала»
        ))

    def _release(self, key) -> None:
        for v in self.voices:
            if v.key == key and v.releasing < 0:
                v.releasing = FADE

    def _hit(self, pad: int, vel: float, semis: float, key) -> None:
        self._start_voice(pad, vel, semis, key)
        self.seq.record_hit(pad)

    def _handle(self, cmd: str, pad: int, vel: float, semis: float, key) -> None:
        if cmd == "on":
            self._hit(pad, vel, semis, key)
        elif cmd == "off":
            if self.pads[pad].mode in (Mode.GATE, Mode.LOOP):
                self._release(key)
        elif cmd == "rep_on":
            if not self._repeat:
                self._repeat_until = 0.0              # первый удар — сразу
            self._repeat[key] = (pad, vel, semis)
        elif cmd == "rep_off":
            self._repeat.pop(key, None)
        elif cmd == "panic":
            self._repeat.clear()
            for v in self.voices:
                v.releasing = FADE

    def _repeat_ticks(self, frames: int) -> list[int]:
        if not self._repeat:
            return []
        every = RATE * 60.0 / self.seq.bpm / REPEAT_RATES[self.repeat_rate]
        out, pos = [], self._repeat_until
        while pos < frames:
            out.append(int(pos))
            pos += every
        self._repeat_until = pos - frames
        return out

    def _render_voice(self, v: Voice, out: np.ndarray, a: int, b: int, tune: float) -> bool:
        """Подмешать голос в out[a:b]. Вернуть False, если голос закончился."""
        n = b - a
        rate = v.rate * tune
        idx = v.pos + np.arange(n, dtype=np.float64) * rate
        if v.loop:
            span = v.end - v.loop_start
            idx = np.where(idx >= v.loop_start, v.loop_start + (idx - v.loop_start) % span, idx)
            alive = n
        else:
            alive = int(np.searchsorted(idx, v.end - 1))
        i0 = idx[:alive]
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
        out[a:a + alive, 0] += chunk[:, 0] * v.gl
        out[a:a + alive, 1] += chunk[:, 1] * v.gr
        v.pos += n * rate
        if v.loop and v.pos >= v.end:
            v.pos = v.loop_start + (v.pos - v.loop_start) % (v.end - v.loop_start)
        return not done and (v.loop or alive == n)

    def _apply_filter(self, out: np.ndarray) -> None:
        """DJ-фильтр: фейдер вниз — глушит верха, вверх — срезает низ, посередине выкл."""
        f = round(self.filter, 2)
        if butter is None or abs(f) < 0.03:
            self._filt, self._filt_key = None, None
            return
        if f != self._filt_key:
            if f < 0:
                cut, kind = 18000 * (200 / 18000) ** (-f), "lowpass"     # 18 кГц → 200 Гц
            else:
                cut, kind = 30 * (6000 / 30) ** f, "highpass"           # 30 Гц → 6 кГц
            b, a = butter(2, cut / (RATE / 2), kind)
            zi = (self._filt[2] if self._filt is not None and len(self._filt[2]) == 2
                  else np.zeros((2, 2)))
            self._filt, self._filt_key = (b, a, zi), f
        b, a, zi = self._filt
        for c in range(2):
            out[:, c], zi[:, c] = lfilter(b, a, out[:, c], zi=zi[:, c])

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
        tune = 2 ** (self.tune / 12)
        # удары секвенсора и NOTE REPEAT — с точностью до кадра: режем блок на куски
        cuts = [(o, p, 1.0, 0.0, p, False) for o, p in self.seq.advance(frames)]
        for o in self._repeat_ticks(frames):
            cuts += [(o, p, vel, semis, key, True) for key, (p, vel, semis) in list(self._repeat.items())]
        bounds = sorted({0, frames, *(c[0] for c in cuts)})
        for a, b in zip(bounds[:-1], bounds[1:]):
            for off, pad, vel, semis, key, rec in cuts:
                if off == a:
                    if rec:
                        self._hit(pad, vel, semis, key)
                    else:
                        self._start_voice(pad, vel, semis, key)
            self.voices = [v for v in self.voices if self._render_voice(v, out, a, b, tune)]
        self._clock += frames
        self._apply_filter(out)
        out *= self.master
        np.tanh(out, out=out)                     # мягкий ограничитель вместо хрипа
        self.level = float(np.max(np.abs(out))) if frames else 0.0
        self.playing_pads = {v.pad for v in self.voices if v.releasing < 0}
        return out
