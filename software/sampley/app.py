"""Логика сэмплера: что делают пэды, кнопки и энкодеры в каждом экране.

Экраны:
  PLAY   — играешь на пэдах; энкодеры крутят звук выбранного пэда;
  STEP   — шаговый секвенсор: 16 пэдов = 16 шагов дорожки выбранного пэда;
  SAMPLE — запись нового звука на выбранный пэд;
  KITS   — сохранить / загрузить набор.

Кнопки: SHIFT (держать), REC, PLAY. Четыре энкодера с нажатием.

  без SHIFT                              с SHIFT
  пэд       — играть + выбрать            — только выбрать (без звука)
  PLAY      — старт/стоп секвенсора       — экран STEP и обратно
  REC       — записать звук на пэд;       — экран KITS
              во время игры — дозапись
              ударов в паттерн
  энкодеры  — Громкость, Тон, Старт,      — Общая громкость, Темп,
              Конец выбранного пэда         Свинг, Паттерн
  нажатия   — Заглушить, Тон=0,           — —, тап-темп, —,
              Задом наперёд, Режим          Очистить дорожку пэда
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable

from . import kit as kits
from .controls import Button, Event, Kind
from .engine import Engine, Mode
from .recorder import RecState
from .sequencer import PADS, PATTERNS


class Screen(Enum):
    PLAY = "ИГРА"
    STEP = "ШАГИ"
    SAMPLE = "ЗАПИСЬ"
    KITS = "НАБОРЫ"


# Цвет подсветки по рядам пэдов: барабаны, перкуссия, бас, мелодия.
ROW_COLORS = [(255, 60, 20), (255, 180, 0), (0, 160, 255), (180, 60, 255)]


def _dim(c, k):
    return tuple(int(v * k) for v in c)


class App:
    def __init__(self, engine: Engine, kits_root: str = kits.KITS_DIR,
                 on_shutdown: Callable[[], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.engine = engine
        self.kits_root = kits_root
        self.on_shutdown = on_shutdown
        self.clock = clock
        self.screen = Screen.PLAY
        self.selected = 0
        self.shift = False
        self.kit_name = "встроенный"
        self.kit_cursor = 0
        self.toast = ""
        self._toast_until = 0.0
        self._taps: list[float] = []
        self.battery: int | None = None     # %, заполняет слой железа
        self.charging = False
        self.dirty = True                   # экран надо перерисовать

    # --- вспомогательное ----------------------------------------------------
    @property
    def pad(self):
        return self.engine.pads[self.selected]

    def say(self, text: str, sec: float = 1.5) -> None:
        self.toast = text
        self._toast_until = self.clock() + sec
        self.dirty = True

    def tick(self) -> None:
        """Вызывать ~30 раз в секунду из главного цикла."""
        if self.toast and self.clock() > self._toast_until:
            self.toast = ""
            self.dirty = True
        rec = self.engine.recorder
        if self.screen is Screen.SAMPLE:
            self.dirty = True                       # индикатор уровня живой
            if rec.state is RecState.DONE:
                s = rec.take(f"Запись {self.selected + 1}")
                if s is None or s.frames < 100:
                    self.say("Тишина — ничего не записалось")
                else:
                    self.pad.sample, self.pad.start, self.pad.end = s, 0.0, 1.0
                    self.say(f"Записано {s.seconds:.1f} с → пэд {self.selected + 1}")
                self.screen = Screen.PLAY
        if self.engine.seq.playing or self.engine.voices:
            self.dirty = True

    def kit_items(self) -> list[str]:
        return ["+ Сохранить как новый", f"Сохранить «{self.kit_name}»"] + kits.list_kits(self.kits_root)

    # --- события ------------------------------------------------------------
    def handle(self, ev: Event) -> None:
        self.dirty = True
        if ev.kind is Kind.PAD:
            self._pad(ev)
        elif ev.kind is Kind.BUTTON:
            if ev.button is Button.SHIFT:
                self.shift = bool(ev.value)
            elif ev.value:
                self._button(ev.button)
        elif ev.kind is Kind.ENCODER:
            self._encoder(ev.index, ev.value)
        elif ev.kind is Kind.ENC_PUSH and ev.value:
            self._push(ev.index)
        elif ev.kind is Kind.POWER and not ev.value:
            self.shutdown()

    def _pad(self, ev: Event) -> None:
        i = ev.index
        if not ev.value:
            if self.screen is Screen.PLAY and not self.shift:
                self.engine.note_off(i)
            return
        if self.shift or self.screen is Screen.KITS:
            self.selected = i
            return
        if self.screen is Screen.STEP:
            on = self.engine.seq.pattern.toggle(self.selected, i)
            if on and not self.engine.seq.playing:
                self.engine.note_on(self.selected, ev.velocity)    # услышать, что поставил
            return
        if self.screen is Screen.SAMPLE:
            self.selected = i                                      # сменить пэд, куда пишем
            return
        self.selected = i
        self.engine.note_on(i, ev.velocity)

    def _button(self, b: Button) -> None:
        seq, rec = self.engine.seq, self.engine.recorder
        if b is Button.PLAY:
            if self.shift:
                self.screen = Screen.PLAY if self.screen is Screen.STEP else Screen.STEP
            else:
                self.say("▶ Играет" if seq.toggle() else "■ Стоп", 0.8)
        elif b is Button.REC:
            if self.shift:
                self.screen = Screen.PLAY if self.screen is Screen.KITS else Screen.KITS
                self.kit_cursor = 0
            elif self.screen is Screen.SAMPLE:
                if rec.state is RecState.RECORDING:
                    rec.stop()                                     # tick() заберёт сэмпл
                else:
                    rec.cancel()
                    self.screen = Screen.PLAY
                    self.say("Запись отменена")
            elif self.screen is Screen.KITS:
                self.screen = Screen.PLAY
            elif seq.playing:
                seq.recording = not seq.recording
                self.say("● Дозапись в паттерн" if seq.recording else "Дозапись выкл", 1.0)
            else:
                self.screen = Screen.SAMPLE
                rec.arm()

    def _encoder(self, enc: int, clicks: int) -> None:
        seq, p = self.engine.seq, self.pad
        if self.screen is Screen.KITS:
            if enc == 0:
                self.kit_cursor = max(0, min(len(self.kit_items()) - 1, self.kit_cursor + clicks))
            return
        if self.screen is Screen.SAMPLE:
            if enc == 0:
                r = self.engine.recorder
                r.threshold = round(max(0.005, min(0.5, r.threshold + clicks * 0.005)), 3)
            return
        if self.shift:
            if enc == 0:
                self.engine.master = round(max(0.0, min(1.0, self.engine.master + clicks * 0.02)), 2)
            elif enc == 1:
                seq.bpm = max(40, min(300, seq.bpm + clicks))
            elif enc == 2:
                seq.swing = round(max(0.0, min(0.6, seq.swing + clicks * 0.02)), 2)
            elif enc == 3:
                target = (seq.queued if seq.queued is not None else seq.current) + clicks
                target %= PATTERNS
                if seq.playing:
                    seq.queued = target                            # сменится с начала такта
                else:
                    seq.current, seq.queued = target, None
            return
        if enc == 0:
            p.volume = round(max(0.0, min(1.0, p.volume + clicks * 0.02)), 2)
        elif enc == 1:
            p.pitch = max(-24, min(24, p.pitch + clicks))
        elif enc == 2:
            p.start = round(max(0.0, min(p.end - 0.01, p.start + clicks * 0.005)), 3)
        elif enc == 3:
            p.end = round(max(p.start + 0.01, min(1.0, p.end + clicks * 0.005)), 3)

    def _push(self, enc: int) -> None:
        p = self.pad
        if self.screen is Screen.KITS:
            if enc == 0:
                self._kit_action()
            return
        if self.screen is Screen.SAMPLE:
            if enc == 0 and self.engine.recorder.state is RecState.ARMED:
                self.engine.recorder.start()                       # не ждать звука
            return
        if self.shift:
            if enc == 1:
                self._tap()
            elif enc == 3:
                self.engine.seq.pattern.clear(self.selected)
                self.say(f"Дорожка пэда {self.selected + 1} очищена")
            return
        if enc == 0:
            p.mute = not p.mute
        elif enc == 1:
            p.pitch = 0
        elif enc == 2:
            p.reverse = not p.reverse
        elif enc == 3:
            modes = list(Mode)
            p.mode = modes[(modes.index(p.mode) + 1) % len(modes)]
            self.say(f"Режим: {p.mode.value}", 1.0)

    def _tap(self) -> None:
        now = self.clock()
        self._taps = [t for t in self._taps if now - t < 2.0] + [now]
        if len(self._taps) >= 2:
            gaps = [b - a for a, b in zip(self._taps, self._taps[1:])]
            self.engine.seq.bpm = round(max(40, min(300, 60 / (sum(gaps) / len(gaps)))))
        self.say(f"Темп {self.engine.seq.bpm:g}", 0.8)

    def _kit_action(self) -> None:
        items = self.kit_items()
        i = self.kit_cursor
        if i == 0:
            n = 1
            while f"kit-{n:02d}" in items:
                n += 1
            self.kit_name = f"kit-{n:02d}"
            kits.save_kit(self.engine, self.kit_name, self.kits_root)
            self.say(f"Сохранено: {self.kit_name}")
        elif i == 1:
            kits.save_kit(self.engine, self.kit_name, self.kits_root)
            self.say(f"Сохранено: {self.kit_name}")
        else:
            self.kit_name = items[i]
            kits.load_kit(self.engine, self.kit_name, self.kits_root)
            self.say(f"Загружено: {self.kit_name}")
        self.screen = Screen.PLAY

    def shutdown(self) -> None:
        self.engine.seq.stop()
        self.engine.stop_all()
        try:
            kits.save_kit(self.engine, "autosave", self.kits_root)
        except OSError:
            pass
        self.say("Выключаюсь…", 10)
        if self.on_shutdown:
            self.on_shutdown()

    # --- для экрана и подсветки --------------------------------------------
    def encoder_labels(self) -> list[tuple[str, str]]:
        seq, p, r = self.engine.seq, self.pad, self.engine.recorder
        if self.screen is Screen.SAMPLE:
            return [("Порог", f"{r.threshold:.3f}"), ("", ""), ("", ""), ("", "")]
        if self.screen is Screen.KITS:
            return [("Выбор", "↕"), ("", ""), ("", ""), ("", "")]
        if self.shift:
            pat = f"{seq.current + 1}" + (f"→{seq.queued + 1}" if seq.queued is not None else "")
            return [("Общая", f"{round(self.engine.master * 100)}%"), ("Темп", f"{seq.bpm:g}"),
                    ("Свинг", f"{round(seq.swing * 100)}%"), ("Паттерн", pat)]
        return [("Громк", f"{round(p.volume * 100)}%"), ("Тон", f"{p.pitch:+g}"),
                ("Старт", f"{round(p.start * 100)}%"), ("Конец", f"{round(p.end * 100)}%")]

    def pad_colors(self) -> list[tuple[int, int, int]]:
        eng, seq = self.engine, self.engine.seq
        out = []
        for i in range(PADS):
            if self.screen is Screen.STEP:
                on = seq.pattern.grid[self.selected][i]
                c = ROW_COLORS[self.selected // 4] if on else (0, 0, 0)
                if seq.playing and seq.step == i:
                    c = (255, 255, 255) if on else (40, 40, 40)
            elif self.screen is Screen.SAMPLE:
                c = (255, 0, 0) if i == self.selected else (0, 0, 0)
            else:
                pad = eng.pads[i]
                base = ROW_COLORS[i // 4]
                if pad.sample is None or pad.mute:
                    c = (0, 0, 0)
                elif i in eng.playing_pads:
                    c = (255, 255, 255)
                else:
                    c = _dim(base, 0.6 if i == self.selected else 0.15)
            out.append(c)
        return out
