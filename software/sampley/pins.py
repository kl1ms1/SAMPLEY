"""Карта 40-пиновой гребёнки SAMPLEY v1.

  I2C1  GPIO2/3   — общая шина: аудиокодек WM8960 (0x1A), зарядка BQ25895 (0x6A),
                    датчик заряда MAX17048 (0x36). Свои I2C-устройства — тоже сюда.
  I2S   GPIO18-21 — звук: такт, слово, вход (АЦП→Pi), выход (Pi→ЦАП).
  SPI0  GPIO8/10/11 + DC/RST/подсветка — экран ST7789.
  UART  GPIO14/15 — микроконтроллер кнопок, энкодеров, подсветки и питания.
  GPIO26          — «Pi выключилась» (dtoverlay=gpio-poweroff) → МК гасит 5 В.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pin:
    bcm: int
    phys: int
    function: str
    free: bool = False


PINS: dict[int, Pin] = {p.bcm: p for p in [
    Pin(2, 3, "I2C1 SDA — WM8960, BQ25895, MAX17048"),
    Pin(3, 5, "I2C1 SCL"),
    Pin(4, 7, "свободен (на макетке с UPS-Lite v1.3 — «заряжается»)", True),
    Pin(5, 29, "свободен", True),
    Pin(6, 31, "свободен", True),
    Pin(7, 26, "свободен (SPI0 CE1)", True),
    Pin(8, 24, "SPI0 CE0 — экран CS"),
    Pin(9, 21, "свободен (SPI0 MISO, экрану не нужен)", True),
    Pin(10, 19, "SPI0 MOSI — экран"),
    Pin(11, 23, "SPI0 SCLK — экран"),
    Pin(12, 32, "свободен", True),
    Pin(13, 33, "PWM1 — подсветка экрана"),
    Pin(14, 8, "UART TX → микроконтроллер"),
    Pin(15, 10, "UART RX ← микроконтроллер"),
    Pin(16, 36, "свободен", True),
    Pin(17, 11, "свободен", True),
    Pin(18, 12, "I2S BCLK — WM8960"),
    Pin(19, 35, "I2S LRCLK — WM8960"),
    Pin(20, 38, "I2S DIN — запись с WM8960"),
    Pin(21, 40, "I2S DOUT — звук в WM8960"),
    Pin(22, 15, "свободен", True),
    Pin(23, 16, "свободен", True),
    Pin(24, 18, "экран RST"),
    Pin(25, 22, "экран DC"),
    Pin(26, 37, "Pi выключилась → МК (gpio-poweroff)"),
    Pin(27, 13, "свободен", True),
]}

LCD_DC, LCD_RST, LCD_BL = 25, 24, 13
POWEROFF_SIGNAL = 26
UART_DEVICE = "/dev/serial0"
UART_BAUD = 460800          # быстро: анимации подсветки и вертушки без задержек
I2C_BUS = 1
ADDR_WM8960, ADDR_BQ25895, ADDR_MAX17048 = 0x1A, 0x6A, 0x36
ADDR_CW2015 = 0x62            # датчик заряда в UPS-Lite (макетка)
UPS_LITE_CHARGE = 4           # UPS-Lite v1.3: 1 = идёт зарядка


def free_pins() -> list[Pin]:
    return [p for p in sorted(PINS.values(), key=lambda p: p.phys) if p.free]
