"""Автоопределение платы: одна SD-карта для Pi Zero W и Pi Zero 2 W.

Модель берётся из /proc/device-tree/model. От неё зависит, сколько звуков
движок играет одновременно и какой размер звукового блока (задержка).
Pi Zero W — одно ядро ARMv6, поэтому голосов меньше и блок длиннее.
Raspberry Pi OS Lite **32-bit** — подходит обеим платам.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_PATH = "/proc/device-tree/model"


@dataclass(frozen=True)
class BoardProfile:
    key: str
    name: str
    voices: int          # одновременных звуков
    block: int           # кадров в звуковом блоке: 256 = 5.8 мс, 512 = 11.6 мс
    ui_fps: int
    spi_hz: int          # частота SPI экрана
    simulated: bool = False

    @property
    def latency_ms(self) -> float:
        return self.block / 44100 * 1000 * 2      # блок на вход + блок на выход


PROFILES = {
    # Zero W: одно ядро ARMv6 — 6 голосов и блок подлиннее, иначе звук рвётся
    "zero_w": BoardProfile("zero_w", "Raspberry Pi Zero W / WH", 6, 1024, 15, 32_000_000),
    "zero_2w": BoardProfile("zero_2w", "Raspberry Pi Zero 2 W / WH", 24, 256, 30, 48_000_000),
    "pc": BoardProfile("pc", "Компьютер (симуляция)", 32, 256, 30, 0, simulated=True),
}


def profile_for_model(model: str | None) -> BoardProfile:
    if not model:
        return PROFILES["pc"]
    m = model.strip("\x00 \n").lower()
    if "zero 2" in m:
        return PROFILES["zero_2w"]
    if "raspberry pi" in m:
        # Zero / Zero W и любые незнакомые Pi — осторожный профиль
        return PROFILES["zero_w"]
    return PROFILES["pc"]


def read_model(path: str = MODEL_PATH) -> str | None:
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def detect(path: str = MODEL_PATH) -> tuple[BoardProfile, str | None]:
    model = read_model(path)
    return profile_for_model(model), model
