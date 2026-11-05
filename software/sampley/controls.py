"""События управления и протокол связи с микроконтроллером кнопок.

Пэды, кнопки, 4 энкодера и ползунок питания читает микроконтроллер RP2040
(на макетке — Raspberry Pi Pico). Он же светит RGB-подсветкой пэдов и
управляет питанием. С Pi он говорит по UART (GPIO14/15, 115200) короткими
текстовыми строками — их видно в любом терминале, легко отлаживать:

  МК → Pi                         Pi → МК
  P <пэд 0-15> <1|0> [сила]       L <пэд> <RRGGBB>     цвет подсветки пэда
  B <SHIFT|REC|PLAY> <1|0>        LA <16 × RRGGBB>     все пэды одной строкой
  E <энкодер 0-3> <±щелчки>       Z                    «Pi выключается»
  K <энкодер 0-3> <1|0>           ?                    кто ты (ответ V …)
  S <ON|OFF>                      (ползунок питания)
  V <версия>
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    PAD = "P"
    BUTTON = "B"
    ENCODER = "E"
    ENC_PUSH = "K"
    POWER = "S"
    VERSION = "V"


class Button(Enum):
    SHIFT = "SHIFT"
    REC = "REC"
    PLAY = "PLAY"


@dataclass(frozen=True)
class Event:
    kind: Kind
    index: int = 0                  # пэд / энкодер
    value: int = 0                  # 1/0 нажато/отпущено, или щелчки энкодера
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
                raise ProtocolError(f"нет энкодера {enc}")
            return Event(Kind.ENCODER if tag == "E" else Kind.ENC_PUSH, enc, int(args[1]))
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


def led_line(pad: int, rgb: tuple[int, int, int]) -> str:
    return f"L {pad} {rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}\n"


def leds_line(colors: list[tuple[int, int, int]]) -> str:
    return "LA " + " ".join(f"{r:02X}{g:02X}{b:02X}" for r, g, b in colors) + "\n"


# Клавиатура компьютера в симуляции: пэды — сетка 4×4 как на устройстве.
KEY_PADS = "1234qwerasdfzxcv"
# Энкодеры: пары клавиш «меньше/больше», нажатие — клавиша посередине.
KEY_ENCODERS = [("5", "6"), ("t", "y"), ("g", "h"), ("b", "n")]
KEY_ENC_PUSH = "7ujm"
KEY_BUTTONS = {"shift": Button.SHIFT, "space": Button.PLAY, "return": Button.REC}
