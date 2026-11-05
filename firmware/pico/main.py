# SAMPLEY — прошивка микроконтроллера кнопок (MicroPython, Raspberry Pi Pico / RP2040).
#
# Что делает:
#   * сканирует матрицу 5×5: 16 пэдов, SHIFT/REC/PLAY, нажатия 4 энкодеров;
#   * читает 4 энкодера EC11 (без упора);
#   * светит 16 RGB-светодиодов под пэдами (WS2812 / SK6812);
#   * управляет питанием («защёлка»): ползунок включает стабилизатор 3.3 В
#     этого микроконтроллера, он сразу сам себя «держит» (GP27 HOLD) и
#     включает 5 В → Pi грузится. Ползунок выкл → сказать Pi «выключайся» →
#     дождаться, пока Pi остановится (GPIO26 Pi → GP26 здесь) → снять 5 В и
#     отпустить HOLD: выключается всё, включая этот микроконтроллер.
#     В выключенном состоянии от аккумулятора ничего не тратится.
#   * говорит с Pi по UART текстом (протокол — software/sampley/controls.py).
#
# Залить: Thonny → «MicroPython (Raspberry Pi Pico)» → сохранить как main.py на Pico.
#
# Подключение (вид со стороны Pico):
#   GP0  UART TX  → Pi GPIO15 (RX)        GP12/13  энкодер 1 A/B
#   GP1  UART RX  ← Pi GPIO14 (TX)        GP14/15  энкодер 2 A/B
#   GP2…GP6   строки матрицы (выходы)     GP16/17  энкодер 3 A/B
#   GP7…GP11  столбцы матрицы (входы)     GP18/19  энкодер 4 A/B
#   GP20 данные светодиодов WS2812        GP21     ползунок питания (к GND = ВКЛ)
#   GP22 включение 5 В (EN бустера)       GP26     «Pi выключилась» (GPIO26 Pi)
#   GP27 HOLD — держать своё питание 3.3 В (на плате; на макетке не нужен)
# В матрице на каждой кнопке диод 1N4148W (катод к строке) — чтобы нажатия
# нескольких пэдов сразу читались правильно.

import machine
import neopixel
import time
from machine import Pin, UART

VERSION = "sampley-mcu 1"
# На макетке Pico питается от Pi, бустера нет — управление питанием выключено.
POWER_CONTROL = False
LED_BRIGHTNESS = 0.35          # подсветка ярче — меньше работает от батареи

uart = UART(0, 115200, tx=Pin(0), rx=Pin(1))
rows = [Pin(n, Pin.OUT, value=1) for n in (2, 3, 4, 5, 6)]
cols = [Pin(n, Pin.IN, Pin.PULL_UP) for n in (7, 8, 9, 10, 11)]
enc_pins = [(Pin(a, Pin.IN, Pin.PULL_UP), Pin(b, Pin.IN, Pin.PULL_UP))
            for a, b in ((12, 13), (14, 15), (16, 17), (18, 19))]
leds = neopixel.NeoPixel(Pin(20), 16)
slider = Pin(21, Pin.IN, Pin.PULL_UP)
boost_en = Pin(22, Pin.OUT, value=0 if POWER_CONTROL else 1)
pi_halted = Pin(26, Pin.IN, Pin.PULL_DOWN)
hold = Pin(27, Pin.OUT, value=1)               # первым делом — удержать своё питание

# Что стоит в каждой клетке матрицы (строка, столбец) → строка протокола.
KEYMAP = {}
for r in range(4):
    for c in range(4):
        KEYMAP[(r, c)] = ("P", r * 4 + c)
for i in range(4):
    KEYMAP[(i, 4)] = ("K", i)                          # нажатия энкодеров
KEYMAP[(4, 0)] = ("B", "SHIFT")
KEYMAP[(4, 1)] = ("B", "REC")
KEYMAP[(4, 2)] = ("B", "PLAY")

DEBOUNCE_MS = 5
state = {k: False for k in KEYMAP}
changed_at = {k: 0 for k in KEYMAP}

# Квадратурный декодер: (старое AB, новое AB) → −1 / 0 / +1
QDEC = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)
enc_prev = [(a.value() << 1) | b.value() for a, b in enc_pins]
enc_acc = [0, 0, 0, 0]
STEPS_PER_DETENT = 4          # EC11: 4 перехода на один щелчок


def send(line):
    uart.write(line + "\n")


def scan_keys(now):
    for r, row in enumerate(rows):
        row.value(0)
        time.sleep_us(3)
        for c, col in enumerate(cols):
            key = (r, c)
            if key not in KEYMAP:
                continue
            down = col.value() == 0
            if down != state[key] and time.ticks_diff(now, changed_at[key]) >= DEBOUNCE_MS:
                state[key] = down
                changed_at[key] = now
                kind, idx = KEYMAP[key]
                send("%s %s %d" % (kind, idx, 1 if down else 0))
        row.value(1)


def _enc_irq(_pin):
    # Прерывание на любой фронт A или B: не теряем щелчки при быстром вращении.
    for i, (a, b) in enumerate(enc_pins):
        cur = (a.value() << 1) | b.value()
        if cur != enc_prev[i]:
            enc_acc[i] += QDEC[(enc_prev[i] << 2) | cur]
            enc_prev[i] = cur


for a, b in enc_pins:
    a.irq(_enc_irq, Pin.IRQ_RISING | Pin.IRQ_FALLING)
    b.irq(_enc_irq, Pin.IRQ_RISING | Pin.IRQ_FALLING)


def scan_encoders():
    for i in range(4):
        acc = enc_acc[i]
        if abs(acc) >= STEPS_PER_DETENT:
            clicks = int(acc / STEPS_PER_DETENT)          # к нулю: остаток копится
            irq = machine.disable_irq()
            enc_acc[i] -= clicks * STEPS_PER_DETENT
            machine.enable_irq(irq)
            send("E %d %d" % (i, clicks))


def set_led(i, hexrgb):
    v = int(hexrgb, 16)
    k = LED_BRIGHTNESS
    leds[i] = (int(((v >> 16) & 255) * k), int(((v >> 8) & 255) * k), int((v & 255) * k))


rx = b""


def handle_uart():
    global rx
    n = uart.any()
    if not n:
        return
    rx += uart.read(n)
    dirty = False
    while b"\n" in rx:
        line, rx = rx.split(b"\n", 1)
        parts = line.decode().strip().split()
        if not parts:
            continue
        try:
            if parts[0] == "L" and len(parts) == 3:
                set_led(int(parts[1]), parts[2])
                dirty = True
            elif parts[0] == "LA":
                for i, h in enumerate(parts[1:17]):
                    set_led(i, h)
                dirty = True
            elif parts[0] == "?":
                send("V " + VERSION)
                send("S " + ("ON" if slider.value() == 0 else "OFF"))
            elif parts[0] == "Z":
                pass                                   # Pi сама выключается; ждём pi_halted
        except ValueError:
            pass
    if dirty:
        leds.write()


# --- питание ----------------------------------------------------------------
OFF, ON, STOPPING = 0, 1, 2
power = ON
if POWER_CONTROL:
    boost_en.value(1)                          # раз нас включили — ползунок уже «вкл»
stop_started = 0
STOP_TIMEOUT_MS = 30000


def power_step(now):
    global power, stop_started
    if not POWER_CONTROL:
        return
    want_on = slider.value() == 0
    if power == ON and not want_on:
        send("S OFF")                                  # Pi сохранит кит и выключится
        power, stop_started = STOPPING, now
    elif power == STOPPING:
        timeout = time.ticks_diff(now, stop_started) > STOP_TIMEOUT_MS
        if pi_halted.value() or timeout:
            time.sleep_ms(1500)                        # дать карте памяти дописать
            leds.fill((0, 0, 0))
            leds.write()
            boost_en.value(0)
            hold.value(0)                          # отпустить защёлку: питание МК пропадёт
            power = OFF


leds.fill((0, 0, 0))
leds.write()
send("V " + VERSION)
while True:
    now = time.ticks_ms()
    power_step(now)
    if power == OFF:
        # Сюда попадаем, только если ползунок снова включили, пока гасли
        # (защёлка ещё держится через ползунок): включаемся заново.
        if slider.value() == 0:
            hold.value(1)
            boost_en.value(1)
            power = ON
        time.sleep_ms(20)
        continue
    scan_keys(now)
    scan_encoders()
    handle_uart()
