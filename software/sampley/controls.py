"""События управления и протокол связи с микроконтроллером кнопок.

Пэды, кнопки, крутилки, фейдер и ручку громкости читает микроконтроллер
RP2040 (на макетке — Raspberry Pi Pico). Он же светит подсветкой пэдов и
кнопок и управляет питанием. С Pi говорит по UART (GPIO14/15, 115200)
короткими текстовыми строками — их видно в любом терминале:

  МК → Pi                         Pi → МК
  P <пэд 0-15> <1|0> [сила]       LA <цвета RRGGBB …>  вся подсветка: 16 пэдов,
  B <КНОПКА> <1|0>                                     потом кнопки (BUTTON_LEDS)
  E <0-3> <±щелчки>               Z                    «Pi выключается»
  K <0-3> <1|0>  нажатие          ?                    кто ты (ответ V …)
  A <0|1> <0-1023>  фейдер / громкость
  S <ON|OFF>   ползунок питания
  V <версия>

Крутилки: 0–2 — K1…K3 под экраном, 3 — энкодер DATA слева от экрана.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    PAD = "P"
    BUTTON = "B"
    ENCODER = "E"
    ENC_PUSH = "K"
    ANALOG = "A"
    POWER = "S"
    VERSION = "V"


class Button(Enum):
    SHIFT = "SHIFT"
    PLAY = "PLAY"
    STOP = "STOP"
    REC = "REC"
    SAMPLE = "SAMPLE"      # записать звук на пэд
    STEP = "STEP"          # шаговый секвенсор
    CHOP = "CHOP"          # нарезать звук по пэдам
    MUTE = "MUTE"          # пэды глушат/включают свои дорожки
    MODE = "MODE"          # режим пэда: удар / держать / луп
    LEVELS = "LEVELS"      # 16 LEVELS: один звук на 16 высотах
    BANK = "BANK"          # банк пэдов A–D
    REPEAT = "REPEAT"      # NOTE REPEAT (держать)
    TAP = "TAP"            # тап-темп
    BROWSE = "BROWSE"      # библиотека звуков
    KITS = "KITS"          # наборы


# Порядок светодиодов кнопок в цепочке после 16 пэдов.
BUTTON_LEDS = [Button.SHIFT, Button.PLAY, Button.STOP, Button.REC, Button.SAMPLE, Button.STEP,
               Button.CHOP, Button.MUTE, Button.MODE, Button.LEVELS, Button.BANK, Button.REPEAT,
               Button.TAP, Button.BROWSE, Button.KITS]

FADER, VOLUME = 0, 1
WHEEL = 3


@dataclass(frozen=True)
class Event:
    kind: Kind
    index: int = 0                  # пэд / крутилка / аналоговый канал
    value: int = 0                  # 1/0, щелчки, или 0…1023
    button: Button | None = None
    velocity: float = 1.0
    text: str = ""


class ProtocolError(ValueError):
    pass


def parse(line: str) -> Event:
    """Строка от микроконтроллера → событие."""
    parts = line.strip().split()
    if not parts:
        raise ProtocolError("пустая строка")
    tag, args = parts[0], parts[1:]
    try:
        if tag == "P":
            pad, down = int(args[0]), int(args[1])
            if not 0 <= pad < 16:
                raise ProtocolError(f"нет пэда {pad}")
            vel = int(args[2]) / 127 if len(args) > 2 else 1.0
            return Event(Kind.PAD, pad, down, velocity=max(0.0, min(1.0, vel)))
        if tag == "B":
            return Event(Kind.BUTTON, value=int(args[1]), button=Button(args[0]))
        if tag in ("E", "K"):
            enc = int(args[0])
            if not 0 <= enc < 4:
                raise ProtocolError(f"нет крутилки {enc}")
            return Event(Kind.ENCODER if tag == "E" else Kind.ENC_PUSH, enc, int(args[1]))
        if tag == "A":
            ch, v = int(args[0]), int(args[1])
            if ch not in (FADER, VOLUME) or not 0 <= v <= 1023:
                raise ProtocolError(f"аналог: {ch} {v}")
            return Event(Kind.ANALOG, ch, v)
        if tag == "S":
            if args[0] not in ("ON", "OFF"):
                raise ProtocolError(f"ползунок: {args[0]}")
            return Event(Kind.POWER, value=1 if args[0] == "ON" else 0)
        if tag == "V":
            return Event(Kind.VERSION, text=" ".join(args))
    except (IndexError, ValueError) as exc:
        if isinstance(exc, ProtocolError):
            raise
        raise ProtocolError(f"не понял «{line.strip()}»: {exc}") from None
    raise ProtocolError(f"неизвестная команда «{tag}»")


def leds_line(colors: list[tuple[int, int, int]]) -> str:
    return "LA " + " ".join(f"{r:02X}{g:02X}{b:02X}" for r, g, b in colors) + "\n"


# --- клавиатура компьютера в симуляции ---------------------------------------
KEY_PADS = "1234qwerasdfzxcv"                 # сетка 4×4 как на устройстве
KEY_ENCODERS = [("5", "6"), ("t", "y"), ("g", "h"), ("left", "right")]   # K1, K2, K3, DATA
KEY_ENC_PUSH = ["7", "u", "j", "down"]
KEY_BUTTONS = {
    "shift": Button.SHIFT, "space": Button.PLAY, "backspace": Button.STOP, "return": Button.REC,
    "f1": Button.SAMPLE, "f2": Button.STEP, "f3": Button.CHOP, "f4": Button.MUTE, "f5": Button.MODE,
    "f6": Button.LEVELS, "f7": Button.BANK, "tab": Button.REPEAT, "f8": Button.TAP,
    "f9": Button.BROWSE, "f10": Button.KITS,
}
KEY_FADER = ("[", "]")                        # фейдер вниз / вверх
