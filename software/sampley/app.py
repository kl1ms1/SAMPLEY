"""Логика сэмплера: что делают пэды, кнопки и крутилки в каждом экране.

Экраны: PLAY (играть), STEP (шаги), SAMPLE (запись), CHOP (нарезка),
BROWSE (библиотека звуков), KITS (наборы).

Главный сценарий — как на улице с MPC: SAMPLE → тапнул пэд → записал
звук → CHOP → порезал по пэдам → играешь бит, пишешь его в паттерн.

Кнопки (подробно — docs/concept.md):
  SHIFT  держать — вторая функция всего остального
  PLAY   старт (SHIFT — с начала)       STOP  стоп; ещё раз — заглушить всё
  REC    дозапись ударов в паттерн (при стопе — взвести, запись пойдёт с PLAY)
  SAMPLE запись звука на пэд            CHOP  нарезать звук пэда по банку
  STEP   шаговый секвенсор              MUTE  пэды глушат свои дорожки
  MODE   режим пэда (SHIFT — группа глушения; в CHOP — авто/ровно)
  LEVELS один звук на 16 высотах        BANK  банк A–D (SHIFT — назад)
  REPEAT держать + пэд — дробь в темп (SHIFT — 1/8, 1/16, 1/16т, 1/32)
  TAP    тап-темп (SHIFT — фейдер: тон / фильтр)
  BROWSE библиотека записей и WAV       KITS  сохранить / загрузить набор
  STUTTER держать — повтор куска звука «а-а-а-а» (SHIFT — зафиксировать)
Вертушки (два диска по бокам экрана, как у диджея): на каждой лежит свой пэд.
Палец сверху + крутишь — скретч, отпустил — играет дальше; крутишь за край —
подгонка скорости. Палец на вертушке + пэд — положить этот пэд на вертушку.
SHIFT + вертушка — DJ-фильтр. Пока держишь STUTTER, правая вертушка меняет
длину повтора (1/4 … 1/64, «разгон»). В CHOP левая двигает начало среза.
Крутилки K1–K3 — то, что подписано внизу экрана; энкодер DATA (слева от экрана) — темп / выбор.
Фейдер — общий тон или DJ-фильтр. Ручка VOLUME — общая громкость.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable

from . import kit as kits
from . import library
from .chop import Chopper
from .controls import BUTTON_LEDS, FADER, VOLUME, Button, Event, Kind
from .engine import REPEAT_RATES, STUTTER_DIVS, Engine, Mode
from .recorder import RecState
from .sample import load_wav
from .sequencer import BANK_SIZE, BANKS, PADS, PATTERNS

PREVIEW = PADS                  # служебный пэд для прослушки (срезы, библиотека)
BANK_NAMES = "ABCD"


class Screen(Enum):
    PLAY = "ИГРА"
    STEP = "ШАГИ"
    SAMPLE = "ЗАПИСЬ"
    CHOP = "НАРЕЗКА"
    BROWSE = "ЗВУКИ"
    KITS = "НАБОРЫ"


SCREEN_BUTTON = {Screen.SAMPLE: Button.SAMPLE, Screen.STEP: Button.STEP, Screen.CHOP: Button.CHOP,
                 Screen.BROWSE: Button.BROWSE, Screen.KITS: Button.KITS}

# Цвет подсветки по рядам пэдов: барабаны, перкуссия, бас, мелодия.
ROW_COLORS = [(255, 60, 20), (255, 180, 0), (0, 160, 255), (180, 60, 255)]
BANK_COLORS = [(255, 60, 20), (0, 200, 80), (0, 160, 255), (220, 60, 255)]


def _dim(c, k):
    return tuple(int(v * k) for v in c)


def level_semis(i: int) -> int:
    """16 LEVELS: левый нижний пэд — исходный тон, правый верхний — +15."""
    r, c = divmod(i, 4)
    return (3 - r) * 4 + c


class App:
    def __init__(self, engine: Engine, kits_root: str = kits.KITS_DIR,
                 samples_root: str = library.SAMPLES_DIR,
                 on_shutdown: Callable[[], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.engine = engine
        while len(engine.pads) <= PREVIEW:
            engine.pads.append(type(engine.pads[0])())
        self.kits_root = kits_root
        self.samples_root = samples_root
        self.on_shutdown = on_shutdown
        self.clock = clock
        self.screen = Screen.PLAY
        self.bank = 0
        self.selected = 0                   # номер пэда 0…63 (с учётом банка)
        self.shift = False
        self.mute_mode = False
        self.levels_mode = False
        self.repeat_held = False
        self.stutter_latched = False
        self.stutter_held = False
        self._jog_acc = 0                   # копим поворот правой вертушки для ступенек STUTTER
        self.jog_touch = [False, False]
        self.decks = [j["pad"] for j in engine.jogs]
        self.fader_mode = "Тон"
        self.fader = 0.5
        self.chopper: Chopper | None = None
        self.browse_items: list[str] = []
        self.browse_cursor = 0
        self.kit_name = "встроенный"
        self.kit_cursor = 0
        self.toast = ""
        self._toast_until = 0.0
        self._taps: list[float] = []
        self._held: dict[int, tuple[int, object, bool]] = {}    # физ. пэд → (пэд, ключ голоса, repeat)
        self.battery: int | None = None     # %, заполняет слой железа
        self.charging = False
        self.dirty = True                   # экран надо перерисовать

    # --- вспомогательное ----------------------------------------------------
    @property
    def pad(self):
        return self.engine.pads[self.selected]

    def abs_pad(self, i: int) -> int:
        return self.bank * BANK_SIZE + i

    def say(self, text: str, sec: float = 1.5) -> None:
        self.toast = text
        self._toast_until = self.clock() + sec
        self.dirty = True

    def go(self, screen: Screen) -> None:
        self.screen = screen
        self.dirty = True

    def preview(self, sample, start: float = 0.0, end: float = 1.0) -> None:
        p = self.engine.pads[PREVIEW]
        p.sample, p.start, p.end, p.mode, p.volume = sample, start, end, Mode.ONESHOT, 0.8
        p.pitch, p.reverse, p.mute = 0.0, False, False
        self.engine.note_on(PREVIEW)

    def tick(self) -> None:
        """Вызывать ~30 раз в секунду из главного цикла."""
        if self.toast and self.clock() > self._toast_until:
            self.toast = ""
            self.dirty = True
        rec = self.engine.recorder
        if self.screen is Screen.SAMPLE:
            self.dirty = True                       # индикатор уровня живой
            if rec.state is RecState.DONE:
                s = rec.take(f"Запись {self.selected % BANK_SIZE + 1}{BANK_NAMES[self.selected // BANK_SIZE]}")
                if s is None or s.frames < 100:
                    self.say("Тишина — ничего не записалось")
                else:
                    try:
                        library.save_recording(s, self.samples_root)
                    except OSError as exc:
                        print(f"[запись] не сохранилась на карту: {exc}")
                    p = self.pad
                    p.sample, p.start, p.end, p.pitch, p.reverse, p.label = s, 0.0, 1.0, 0.0, False, None
                    self.say(f"Записано {s.seconds:.1f} с · CHOP — порезать", 2.5)
                self.go(Screen.PLAY)
        if self.engine.seq.playing or self.engine.voices:
            self.dirty = True

    def kit_items(self) -> list[str]:
        return ["+ Сохранить как новый", f"Сохранить «{self.kit_name}»"] + kits.list_kits(self.kits_root)

    # --- события ------------------------------------------------------------
    def handle(self, ev: Event) -> None:
        self.dirty = True
        if ev.kind is Kind.PAD:
            self._pad_down(ev) if ev.value else self._pad_up(ev.index)
        elif ev.kind is Kind.BUTTON:
            if ev.button is Button.SHIFT:
                self.shift = bool(ev.value)
            elif ev.button is Button.REPEAT and not self.shift:
                self._repeat_button(bool(ev.value))
            elif ev.button is Button.STUTTER:
                self._stutter_button(bool(ev.value))
            elif ev.value:
                self._button(ev.button)
        elif ev.kind is Kind.ENCODER:
            self._encoder(ev.index, ev.value)
        elif ev.kind is Kind.ENC_PUSH and ev.value:
            self._push(ev.index)
        elif ev.kind is Kind.ANALOG:
            self._analog(ev.index, ev.value / 1023)
        elif ev.kind is Kind.JOG:
            self._jog(ev.index, ev.value)
        elif ev.kind is Kind.JOG_TOUCH:
            self.jog_touch[ev.index] = bool(ev.value)
            self.engine.jog_touch(ev.index, bool(ev.value))
        elif ev.kind is Kind.POWER and not ev.value:
            self.shutdown()

    def _pad_down(self, ev: Event) -> None:
        i, vel = ev.index, ev.velocity
        a = self.abs_pad(i)
        eng, sc = self.engine, self.screen
        if sc is Screen.PLAY and any(self.jog_touch):              # палец на вертушке + пэд
            w = 0 if self.jog_touch[0] else 1
            eng.set_deck(w, a)
            self.decks[w] = a
            self.say(f"{self.pad_label(a)} → вертушка {'L' if w == 0 else 'R'}", 1.0)
            return
        if self.shift or sc in (Screen.KITS, Screen.BROWSE):
            self.selected = a
            return
        if sc is Screen.STEP:
            on = eng.seq.pattern.toggle(self.selected, i)
            if on and not eng.seq.playing:
                eng.note_on(self.selected, vel)                     # услышать, что поставил
            return
        if sc is Screen.SAMPLE:
            self.selected = a                                       # «тапни пэд — пишем на него»
            eng.recorder.start()
            return
        if sc is Screen.CHOP:
            ch = self.chopper
            if ch and i < len(ch.slices):
                ch.cursor = i
                s, e = ch.slices[i]
                self.preview(ch.sample, s / ch.sample.frames, e / ch.sample.frames)
            return
        if self.mute_mode:
            eng.pads[a].mute = not eng.pads[a].mute
            return
        if self.levels_mode:
            pad, key, semis = self.selected, ("lv", i), level_semis(i)
        else:
            self.selected = pad = a
            key, semis = a, 0
        if self.repeat_held:
            eng.repeat_on(pad, vel, semis, key)
        else:
            eng.note_on(pad, vel, semis, key)
        self._held[i] = (pad, key, self.repeat_held)

    def _pad_up(self, i: int) -> None:
        held = self._held.pop(i, None)
        if held is None:
            return
        pad, key, rep = held
        if rep:
            self.engine.repeat_off(key)
        self.engine.note_off(pad, key)

    def _stutter_button(self, down: bool) -> None:
        eng = self.engine
        if down and self.shift:                                     # SHIFT — зафиксировать / снять
            self.stutter_latched = not (self.stutter_latched and eng.stuttering)
            eng.stutter_on() if self.stutter_latched else eng.stutter_off()
            self.say(f"STUTTER {eng.stutter_div} — держится" if self.stutter_latched else "STUTTER выкл", 1.0)
        elif down:
            self.stutter_latched, self.stutter_held = False, True
            self._jog_acc = 0
            eng.stutter_on()
        else:
            self.stutter_held = False
            if not self.stutter_latched:
                eng.stutter_off()

    @property
    def stutter_active(self) -> bool:
        return self.stutter_held or self.stutter_latched

    def _jog(self, wheel: int, counts: int) -> None:
        eng = self.engine
        if self.screen is Screen.CHOP and self.chopper and wheel == 0:
            self.chopper.nudge(0, round(counts / 40))                # точная подгонка начала среза
            return
        if self.shift:                                              # SHIFT — DJ-фильтр
            eng.filter = round(max(-1.0, min(1.0, eng.filter + counts * 0.0006)), 3)
            return
        if wheel == 1 and self.stutter_active:                      # «разгон» повторов
            self._jog_acc += counts
            if abs(self._jog_acc) >= 400:                           # ступенька ≈ каждые 35°
                step = 1 if self._jog_acc > 0 else -1
                self._jog_acc = 0
                divs = list(STUTTER_DIVS)
                eng.stutter_div = divs[max(0, min(len(divs) - 1, divs.index(eng.stutter_div) + step))]
                self.say(f"Повтор {eng.stutter_div}", 0.6)
            return
        eng.jog(wheel, counts)

    def _repeat_button(self, down: bool) -> None:
        self.repeat_held = down
        for i, (pad, key, rep) in list(self._held.items()):
            if down and not rep:
                semis = level_semis(i) if isinstance(key, tuple) else 0
                self.engine.repeat_on(pad, 1.0, semis, key)
                self._held[i] = (pad, key, True)
            elif not down and rep:
                self.engine.repeat_off(key)
                self._held[i] = (pad, key, False)

    def _button(self, b: Button) -> None:
        eng, seq, rec = self.engine, self.engine.seq, self.engine.recorder
        sh = self.shift
        if b is Button.PLAY:
            if sh or not seq.playing:
                seq.start()
                self.say("● Запись в паттерн" if seq.recording else "▶ Играет", 0.8)
        elif b is Button.STOP:
            if seq.playing:
                seq.stop()
            else:
                eng.stop_all()
        elif b is Button.REC:
            seq.recording = not seq.recording
            if seq.recording and not seq.playing:
                self.say("● Готов писать — жми PLAY", 1.2)
            else:
                self.say("● Дозапись в паттерн" if seq.recording else "Дозапись выкл", 1.0)
        elif b is Button.SAMPLE:
            if self.screen is Screen.SAMPLE:
                if rec.state is RecState.RECORDING:
                    rec.stop()                                     # tick() заберёт звук
                else:
                    rec.cancel()
                    self.go(Screen.PLAY)
            else:
                self.go(Screen.SAMPLE)
                rec.arm()
        elif b is Button.STEP:
            self.go(Screen.PLAY if self.screen is Screen.STEP else Screen.STEP)
        elif b is Button.CHOP:
            if self.screen is Screen.CHOP:
                self.go(Screen.PLAY)
            elif self.pad.sample is None:
                self.say("Пэд пустой — сначала SAMPLE")
            else:
                self.chopper = Chopper(self.pad.sample)
                self.go(Screen.CHOP)
        elif b is Button.MUTE:
            self.mute_mode = not self.mute_mode
            self.levels_mode = False
            self.go(Screen.PLAY)
        elif b is Button.LEVELS:
            self.levels_mode = not self.levels_mode
            self.mute_mode = False
            self.go(Screen.PLAY)
        elif b is Button.MODE:
            if self.screen is Screen.CHOP and self.chopper:
                self.chopper.toggle_mode()
            elif sh:
                self.pad.choke = (self.pad.choke + 1) % 5
                self.say(f"Группа глушения: {self.pad.choke or 'нет'}", 1.0)
            else:
                modes = list(Mode)
                self.pad.mode = modes[(modes.index(self.pad.mode) + 1) % len(modes)]
                self.say(f"Режим: {self.pad.mode.value}", 1.0)
        elif b is Button.BANK:
            self.bank = (self.bank + (-1 if sh else 1)) % BANKS
            self.selected = self.bank * BANK_SIZE + self.selected % BANK_SIZE
            self.say(f"Банк {BANK_NAMES[self.bank]}", 0.8)
        elif b is Button.REPEAT:                                    # сюда — только с SHIFT
            rates = list(REPEAT_RATES)
            eng.repeat_rate = rates[(rates.index(eng.repeat_rate) + 1) % len(rates)]
            self.say(f"Повтор {eng.repeat_rate}", 0.8)
        elif b is Button.TAP:
            if sh:
                self.fader_mode = "Фильтр" if self.fader_mode == "Тон" else "Тон"
                eng.tune, eng.filter = 0.0, 0.0
                self._analog(FADER, self.fader)
                self.say(f"Фейдер: {self.fader_mode}", 1.0)
            else:
                self._tap()
        elif b is Button.BROWSE:
            if self.screen is Screen.BROWSE:
                self.go(Screen.PLAY)
            else:
                self.browse_items = library.list_samples(self.samples_root)
                self.browse_cursor = 0
                self.go(Screen.BROWSE)
        elif b is Button.KITS:
            self.go(Screen.PLAY if self.screen is Screen.KITS else Screen.KITS)
            self.kit_cursor = 0

    def _encoder(self, enc: int, clicks: int) -> None:
        eng, seq, p, sc = self.engine, self.engine.seq, self.pad, self.screen
        if sc is Screen.KITS:
            self.kit_cursor = max(0, min(len(self.kit_items()) - 1, self.kit_cursor + clicks))
            return
        if sc is Screen.BROWSE:
            if self.browse_items:
                self.browse_cursor = max(0, min(len(self.browse_items) - 1, self.browse_cursor + clicks))
            return
        if sc is Screen.SAMPLE:
            r = eng.recorder
            r.threshold = round(max(0.005, min(0.5, r.threshold + clicks * 0.005)), 3)
            return
        if sc is Screen.CHOP and self.chopper:
            ch = self.chopper
            if enc == 0:
                ch.amount(clicks)
            elif enc in (1, 2):
                ch.nudge(enc - 1, clicks)
            else:
                ch.select(clicks)
                s, e = ch.slices[ch.cursor]
                self.preview(ch.sample, s / ch.sample.frames, e / ch.sample.frames)
            return
        if enc == 3:                                                # DATA — темп
            seq.bpm = round(max(40, min(300, seq.bpm + clicks * (10 if self.shift else 1))))
            return
        if self.shift:
            if enc == 0:
                seq.swing = round(max(0.0, min(0.6, seq.swing + clicks * 0.02)), 2)
            elif enc == 1:
                target = ((seq.queued if seq.queued is not None else seq.current) + clicks) % PATTERNS
                if seq.playing:
                    seq.queued = target                             # сменится с начала такта
                else:
                    seq.current, seq.queued = target, None
            elif enc == 2:
                p.choke = max(0, min(4, p.choke + clicks))
            return
        if enc == 0:
            p.volume = round(max(0.0, min(1.0, p.volume + clicks * 0.02)), 2)
        elif enc == 1:
            p.pitch = max(-24, min(24, p.pitch + clicks))
        elif enc == 2:
            p.pan = round(max(-1.0, min(1.0, p.pan + clicks * 0.05)), 2)

    def _push(self, enc: int) -> None:
        p, sc = self.pad, self.screen
        if sc is Screen.KITS:
            if enc in (0, 3):
                self._kit_action()
            return
        if sc is Screen.BROWSE:
            if enc in (0, 3) and self.browse_items:
                self._browse_load()
            return
        if sc is Screen.SAMPLE:
            if self.engine.recorder.state is RecState.ARMED:
                self.engine.recorder.start()                        # не ждать звука
            return
        if sc is Screen.CHOP and self.chopper:
            ch = self.chopper
            if enc == 3:
                first = self.bank * BANK_SIZE
                n = ch.apply(self.engine, first)
                self.selected = first
                self.go(Screen.PLAY)
                self.say(f"{n} срезов → пэды {BANK_NAMES[self.bank]}1–{BANK_NAMES[self.bank]}{n}", 2.0)
            else:
                s, e = ch.slices[ch.cursor]
                self.preview(ch.sample, s / ch.sample.frames, e / ch.sample.frames)
            return
        if self.shift:
            if enc == 1:
                self.engine.seq.pattern.clear(self.selected)
                self.say("Дорожка пэда очищена")
            return
        if enc == 0:
            p.volume = 0.8
        elif enc == 1:
            p.pitch = 0
        elif enc == 2:
            p.reverse = not p.reverse
            self.say("Задом наперёд" if p.reverse else "Обычно", 0.8)

    def _analog(self, ch: int, v: float) -> None:
        v = max(0.0, min(1.0, v))
        if ch == VOLUME:
            self.engine.master = round(v, 3)
            return
        self.fader = v
        centered = (v - 0.5) * 2                                    # −1…+1
        if abs(centered) < 0.04:                                    # «мёртвая зона» по центру
            centered = 0.0
        if self.fader_mode == "Тон":
            self.engine.tune = round(centered * 12)                 # ±1 октава, по полутонам
        else:
            self.engine.filter = round(centered, 2)

    def _tap(self) -> None:
        now = self.clock()
        self._taps = [t for t in self._taps if now - t < 2.0] + [now]
        if len(self._taps) >= 2:
            gaps = [b - a for a, b in zip(self._taps, self._taps[1:])]
            self.engine.seq.bpm = round(max(40, min(300, 60 / (sum(gaps) / len(gaps)))))
        self.say(f"Темп {self.engine.seq.bpm:g}", 0.8)

    def _browse_load(self) -> None:
        import os
        rel = self.browse_items[self.browse_cursor]
        try:
            s = load_wav(os.path.join(self.samples_root, rel))
        except (OSError, ValueError, EOFError) as exc:
            self.say(f"Не открылся: {exc}")
            return
        p = self.pad
        p.sample, p.start, p.end, p.pitch, p.reverse, p.mute, p.label = s, 0.0, 1.0, 0.0, False, False, None
        self.engine.note_on(self.selected)
        self.say(f"{s.name} → пэд {self.pad_label(self.selected)}", 1.2)

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
        self.go(Screen.PLAY)

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
    @staticmethod
    def pad_label(a: int) -> str:
        return f"{BANK_NAMES[a // BANK_SIZE]}{a % BANK_SIZE + 1}"

    def encoder_labels(self) -> list[tuple[str, str]]:
        seq, p, r, eng = self.engine.seq, self.pad, self.engine.recorder, self.engine
        sc = self.screen
        empty = ("", "")
        if sc is Screen.SAMPLE:
            return [("Порог", f"{r.threshold:.3f}"), empty, empty, ("Старт", "сразу")]
        if sc in (Screen.KITS, Screen.BROWSE):
            return [("Выбор", "↕"), empty, empty, ("Выбор", "OK")]
        if sc is Screen.CHOP and self.chopper:
            ch = self.chopper
            amt = f"{round(ch.sensitivity * 100)}%" if ch.mode.name == "AUTO" else f"{ch.count} шт"
            return [("Авто" if ch.mode.name == "AUTO" else "Кусков", amt), ("Начало", "◀▶"),
                    ("Конец", "◀▶"), ("Срез", f"{ch.cursor + 1}/{len(ch.slices)}")]
        if self.shift:
            pat = f"{seq.current + 1}" + (f"→{seq.queued + 1}" if seq.queued is not None else "")
            return [("Свинг", f"{round(seq.swing * 100)}%"), ("Паттерн", pat),
                    ("Глуш", f"{p.choke or '—'}"), ("Темп", f"{seq.bpm:g}")]
        pan = "C" if abs(p.pan) < 0.01 else (f"L{round(-p.pan * 100)}" if p.pan < 0 else f"R{round(p.pan * 100)}")
        return [("Громк", f"{round(p.volume * 100)}%"), ("Тон", f"{p.pitch:+g}"),
                ("Пан", pan), ("Темп", f"{seq.bpm:g}")]

    def pad_colors(self) -> list[tuple[int, int, int]]:
        eng, seq = self.engine, self.engine.seq
        out = []
        for i in range(BANK_SIZE):
            a = self.abs_pad(i)
            pad = eng.pads[a]
            sc = self.screen
            if sc is Screen.STEP:
                on = seq.pattern.grid[self.selected][i]
                c = ROW_COLORS[(self.selected % BANK_SIZE) // 4] if on else (0, 0, 0)
                if seq.playing and seq.step == i:
                    c = (255, 255, 255) if on else (40, 40, 40)
            elif sc is Screen.SAMPLE:
                rec = eng.recorder.state is RecState.RECORDING
                c = ((255, 0, 0) if rec else (120, 0, 0)) if a == self.selected else (0, 0, 0)
            elif sc is Screen.CHOP and self.chopper:
                n = len(self.chopper.slices)
                c = (255, 255, 255) if i == self.chopper.cursor else (_dim(BANK_COLORS[self.bank], 0.4)
                                                                     if i < n else (0, 0, 0))
            elif sc in (Screen.BROWSE, Screen.KITS):
                c = (255, 255, 255) if a == self.selected else _dim(BANK_COLORS[self.bank], 0.1)
            elif self.mute_mode:
                c = (0, 0, 0) if pad.sample is None else ((150, 0, 0) if pad.mute else (0, 150, 40))
            elif self.levels_mode:
                base = ROW_COLORS[(self.selected % BANK_SIZE) // 4]
                c = _dim(base, 0.15 + 0.85 * level_semis(i) / 15)
                if self.selected in eng.playing_pads and i in self._held:
                    c = (255, 255, 255)
            else:
                base = ROW_COLORS[i // 4]
                if pad.sample is None or pad.mute:
                    c = (0, 0, 0)
                elif a in eng.playing_pads:
                    c = (255, 255, 255)
                else:
                    c = _dim(base, 0.6 if a == self.selected else 0.15)
            out.append(c)
        return out

    def button_colors(self) -> list[tuple[int, int, int]]:
        seq = self.engine.seq
        on = {
            Button.SHIFT: self.shift, Button.PLAY: seq.playing, Button.REC: seq.recording,
            Button.MUTE: self.mute_mode, Button.LEVELS: self.levels_mode, Button.REPEAT: self.repeat_held,
            Button.TAP: seq.playing and seq.step % 4 == 0, Button.STUTTER: self.stutter_active,
        }
        for screen, btn in SCREEN_BUTTON.items():
            on[btn] = self.screen is screen
        color = {Button.PLAY: (0, 255, 60), Button.REC: (255, 0, 0), Button.SAMPLE: (255, 0, 0),
                 Button.STUTTER: (0, 200, 255),
                 Button.BANK: BANK_COLORS[self.bank]}
        out = []
        for b in BUTTON_LEDS:
            c = color.get(b, (255, 140, 0))
            out.append(c if on.get(b) or b is Button.BANK else _dim(c, 0.06))
        return out

    def led_colors(self) -> list[tuple[int, int, int]]:
        """Вся цепочка подсветки: 16 пэдов, потом кнопки в порядке BUTTON_LEDS."""
        return self.pad_colors() + self.button_colors()
