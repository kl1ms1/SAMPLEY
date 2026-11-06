"""Защита аккумулятора: от переразряда, перегрева и вздутия.

Аккумулятор защищён в несколько слоёв — если один не сработает, сработает
следующий:

  1. SAMPLEY (этот файл): при 3 % или 3.40 В аккуратно сохраняется и
     выключается; при перегреве предупреждает и выключается; заряжает
     «бережно» — до 4.10 В вместо 4.20 В, током 0.3C.
  2. Зарядка BQ25895: сама не заряжает холодный (< 0 °C) и горячий (> 45 °C)
     аккумулятор, следит за термодатчиком NTC на самом аккумуляторе.
  3. Защита DW01A + FS8205A на плате: отрубает аккумулятор при 2.4 В,
     4.3 В, перегрузке и коротком замыкании — без всякого софта.
  4. Защитная плата внутри самого аккумулятора (берём только такие) и
     самовосстанавливающийся предохранитель 2 А.

Вздутие Li-Po бывает от перезаряда, глубокого разряда, жары и долгого
хранения на 100 %. Против всех четырёх — пункты выше, плюс в корпусе над
аккумулятором оставлен зазор ≥ 1 мм под мягкой прокладкой: аккумулятор ничем
не зажат и ничего не давит, если всё-таки начнёт пухнуть.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Пороги
SHUTDOWN_PERCENT = 3
SHUTDOWN_VOLTS = 3.40          # под нагрузкой; DW01A отрубит ещё ниже — при 2.4 В
LOW_PERCENT = 15
WARN_HOT_C = 50.0              # корпус в руках — уже горячо
SHUTDOWN_HOT_C = 60.0
COLD_C = 0.0

# «Бережная» зарядка BQ25895: напряжение и ток
CARE_CHARGE_VOLTS = 4.096      # ≈ 90 % ёмкости, но в 2–3 раза больше циклов и меньше риск вздутия
FULL_CHARGE_VOLTS = 4.208
CARE_CHARGE_MA = 1024          # 0.3C для 3000 мА·ч — аккумулятор не греется


class Action(Enum):
    OK = "ok"
    LOW = "мало заряда"
    COLD = "холодно — зарядка ждёт"
    HOT = "горячо"
    SHUTDOWN_EMPTY = "разряжен — выключаюсь"
    SHUTDOWN_HOT = "перегрев — выключаюсь"


@dataclass(frozen=True)
class BatteryState:
    percent: int | None
    volts: float | None
    temp_c: float | None
    charging: bool


def check(st: BatteryState) -> Action:
    """Что делать сейчас. Самое опасное — первым."""
    if st.temp_c is not None and st.temp_c >= SHUTDOWN_HOT_C:
        return Action.SHUTDOWN_HOT
    if not st.charging:
        if st.percent is not None and st.percent <= SHUTDOWN_PERCENT:
            return Action.SHUTDOWN_EMPTY
        if st.volts is not None and st.volts <= SHUTDOWN_VOLTS:
            return Action.SHUTDOWN_EMPTY
    if st.temp_c is not None and st.temp_c >= WARN_HOT_C:
        return Action.HOT
    if st.charging and st.temp_c is not None and st.temp_c < COLD_C:
        return Action.COLD
    if not st.charging and st.percent is not None and st.percent <= LOW_PERCENT:
        return Action.LOW
    return Action.OK


def bq_vreg(volts: float) -> int:
    """Значение регистра 0x06 BQ25895: напряжение заряда (3.840 В + 16 мВ × код), подзаряд −100 мВ."""
    code = max(0, min(63, round((volts - 3.840) / 0.016)))
    return (code << 2) | 0b10            # BATLOWV = 3.0 В, VRECHG = 100 мВ


def bq_ichg(ma: int) -> int:
    """Значение регистра 0x04 BQ25895: ток заряда, 64 мА × код."""
    return max(0, min(0x7F, ma // 64))


def ntc_celsius(ts_percent: float, beta: float = 3435, r_top: float = 5230, r_bottom: float = 30100) -> float | None:
    """Температура аккумулятора из напряжения TS (в % от REGN) по делителю NTC 10 кОм на плате."""
    import math
    v = ts_percent / 100
    if not 0.05 < v < 0.95:
        return None
    # TS = R∥ / (R_top + R∥), где R∥ = NTC ∥ R_bottom
    r_par = r_top * v / (1 - v)
    if r_par >= r_bottom:
        return None
    r_ntc = r_par * r_bottom / (r_bottom - r_par)
    return 1 / (1 / 298.15 + math.log(r_ntc / 10000) / beta) - 273.15
