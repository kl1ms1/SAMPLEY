"""Железо: экран, звук, связь с микроконтроллером, аккумулятор.

На Pi используются spidev, gpiozero, pyserial, smbus2, sounddevice.
Если чего-то нет (запуск на ПК) — подставляется заглушка, программа
продолжает работать без этой части.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time

from . import pins
from .controls import Event, ProtocolError, leds_line, parse


# --- экран ST7789 2.0″ 320×240 ----------------------------------------------
class ST7789:
    """Минимальный драйвер ST7789 по SPI (без fbtft и оверлеев)."""

    def __init__(self, spi_hz: int, width: int = 320, height: int = 240):
        import spidev  # type: ignore
        from gpiozero import DigitalOutputDevice, PWMOutputDevice  # type: ignore
        self.w, self.h = width, height
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = spi_hz
        self.spi.mode = 0
        self.dc = DigitalOutputDevice(pins.LCD_DC)
        self.rst = DigitalOutputDevice(pins.LCD_RST)
        self.bl = PWMOutputDevice(pins.LCD_BL, frequency=1000)
        self._init()
        self.backlight(0.8)

    def _cmd(self, c: int, data: bytes = b"") -> None:
        self.dc.off()
        self.spi.writebytes([c])
        if data:
            self.dc.on()
            self.spi.writebytes2(data)

    def _init(self) -> None:
        self.rst.off(); time.sleep(0.02); self.rst.on(); time.sleep(0.12)
        self._cmd(0x01); time.sleep(0.15)                 # программный сброс
        self._cmd(0x11); time.sleep(0.12)                 # выйти из сна
        self._cmd(0x3A, b"\x55")                          # 16 бит на точку
        self._cmd(0x36, b"\x60")                          # альбомная ориентация (повернуть: 0xA0)
        self._cmd(0x21)                                   # инверсия — нужна IPS-панелям
        self._cmd(0x13)
        self._cmd(0x29)                                   # включить

    def backlight(self, level: float) -> None:
        self.bl.value = max(0.0, min(1.0, level))

    def show(self, img) -> None:
        from .ui import to_rgb565
        self._cmd(0x2A, bytes([0, 0, (self.w - 1) >> 8, (self.w - 1) & 0xFF]))
        self._cmd(0x2B, bytes([0, 0, (self.h - 1) >> 8, (self.h - 1) & 0xFF]))
        self._cmd(0x2C, to_rgb565(img))


class PNGDisplay:
    """Симуляция: сохраняет кадр в PNG (для проверки без экрана)."""

    def __init__(self, path: str):
        self.path = path

    def show(self, img) -> None:
        img.save(self.path)

    def backlight(self, level: float) -> None:
        pass


# --- микроконтроллер кнопок (UART) ------------------------------------------
class McuLink:
    """Читает события с микроконтроллера в фоне, отправляет ему подсветку."""

    def __init__(self, device: str = pins.UART_DEVICE, baud: int = pins.UART_BAUD):
        import serial  # type: ignore
        self.port = serial.Serial(device, baud, timeout=0.1)
        self.events: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._last_leds = ""
        self._stop = threading.Event()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("?\n")

    def _reader(self) -> None:
        buf = b""
        while not self._stop.is_set():
            buf += self.port.read(64)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    self.events.put(parse(line.decode("ascii", "replace")))
                except ProtocolError as exc:
                    print(f"[МК] {exc}")

    def send(self, line: str) -> None:
        self.port.write(line.encode("ascii"))

    def set_leds(self, colors) -> None:
        line = leds_line(colors)
        if line != self._last_leds:           # не гонять одно и то же 30 раз в секунду
            self.send(line)
            self._last_leds = line

    def close(self) -> None:
        self._stop.set()
        self.port.close()


# --- аккумулятор --------------------------------------------------------------
class Battery:
    """Заряд аккумулятора.

    Своя плата: проценты — MAX17048 (0x36), «заряжается» — BQ25895 (0x6A).
    Макетка с UPS-Lite v1.2/1.3: проценты — CW2015 (0x62), «заряжается» —
    GPIO4 (только у v1.3). Что из этого есть — определяется само.
    """

    def __init__(self):
        from smbus2 import SMBus  # type: ignore
        self.bus = SMBus(pins.I2C_BUS)
        self.kind = None
        for kind, addr in (("max17048", pins.ADDR_MAX17048), ("cw2015", pins.ADDR_CW2015)):
            try:
                self.bus.read_byte_data(addr, 0x04)
                self.kind = kind
                break
            except OSError:
                continue
        if self.kind is None:
            raise OSError("нет датчика заряда (MAX17048 / CW2015)")
        self._ups_pin = None
        if self.kind == "cw2015":
            self.bus.write_byte_data(pins.ADDR_CW2015, 0x0A, 0x00)     # разбудить датчик
            try:
                from gpiozero import DigitalInputDevice  # type: ignore
                self._ups_pin = DigitalInputDevice(pins.UPS_LITE_CHARGE, pull_up=False)
            except Exception:
                pass

    def percent(self) -> int | None:
        addr = pins.ADDR_MAX17048 if self.kind == "max17048" else pins.ADDR_CW2015
        try:
            hi, lo = self.bus.read_i2c_block_data(addr, 0x04, 2)
            return max(0, min(100, round(hi + lo / 256)))
        except OSError:
            return None

    def volts(self) -> float | None:
        try:
            if self.kind == "max17048":
                hi, lo = self.bus.read_i2c_block_data(pins.ADDR_MAX17048, 0x02, 2)
                return ((hi << 8) | lo) * 78.125e-6
            hi, lo = self.bus.read_i2c_block_data(pins.ADDR_CW2015, 0x02, 2)
            return (((hi << 8) | lo) & 0x3FFF) * 305e-6
        except OSError:
            return None

    def temp_c(self) -> float | None:
        """Температура самого аккумулятора по его NTC (через АЦП BQ25895). На UPS-Lite — нет."""
        if self.kind != "max17048":
            return None
        from .power import ntc_celsius
        try:
            raw = self.bus.read_byte_data(pins.ADDR_BQ25895, 0x10) & 0x7F
            return ntc_celsius(21.0 + raw * 0.465)
        except OSError:
            return None

    def setup_care_charging(self, care: bool = True) -> None:
        """Бережная зарядка: до 4.10 В током 0.3C (меньше износ и риск вздутия), АЦП — постоянно."""
        if self.kind != "max17048":
            return
        from .power import CARE_CHARGE_MA, CARE_CHARGE_VOLTS, FULL_CHARGE_VOLTS, bq_ichg, bq_vreg
        try:
            r2 = self.bus.read_byte_data(pins.ADDR_BQ25895, 0x02)
            self.bus.write_byte_data(pins.ADDR_BQ25895, 0x02, r2 | 0xC0)      # АЦП: старт + непрерывно
            self.bus.write_byte_data(pins.ADDR_BQ25895, 0x06,
                                     bq_vreg(CARE_CHARGE_VOLTS if care else FULL_CHARGE_VOLTS))
            self.bus.write_byte_data(pins.ADDR_BQ25895, 0x04, bq_ichg(CARE_CHARGE_MA))
        except OSError:
            pass

    def state(self):
        from .power import BatteryState
        return BatteryState(self.percent(), self.volts(), self.temp_c(), self.charging())

    def charging(self) -> bool:
        if self.kind == "cw2015":
            return bool(self._ups_pin and self._ups_pin.value)
        try:
            stat = (self.bus.read_byte_data(pins.ADDR_BQ25895, 0x0B) >> 3) & 0b11
            return stat in (1, 2)                       # предзаряд / быстрый заряд
        except OSError:
            return False


# --- звук ---------------------------------------------------------------------
class Audio:
    """Дуплексный поток: вход (микрофон/линия) → движок → выход."""

    def __init__(self, engine, block: int, device=None, with_input: bool = True):
        import sounddevice as sd  # type: ignore
        self.engine = engine
        self.xruns = 0
        if device is None:                      # на Pi — звуковая карта WM8960, а не HDMI
            device = next((i for i, d in enumerate(sd.query_devices())
                           if "wm8960" in d["name"].lower()), None)

        def cb_duplex(indata, outdata, frames, t, status):
            if status:
                self.xruns += 1
            outdata[:] = engine.render(frames, indata)

        def cb_out(outdata, frames, t, status):
            if status:
                self.xruns += 1
            outdata[:] = engine.render(frames)

        kw = dict(samplerate=44100, blocksize=block, dtype="float32", device=device, latency="low")
        try:
            if not with_input:
                raise RuntimeError
            self.stream = sd.Stream(channels=2, callback=cb_duplex, **kw)
        except Exception:
            print("[звук] вход недоступен — только воспроизведение")
            self.stream = sd.OutputStream(channels=2, callback=cb_out, **kw)
        self.stream.start()

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


def poweroff() -> None:
    """Аккуратно выключить Pi. Когда система остановится, GPIO26 скажет МК снять 5 В."""
    subprocess.Popen(["sudo", "systemctl", "poweroff"])
