# SAMPLEY — прошивка микроконтроллера кнопок (MicroPython, Raspberry Pi Pico / RP2040).
#
# Что делает:
#   * сканирует матрицу 6×6: 16 пэдов, 15 кнопок, нажатия 3 крутилок и энкодера DATA;
#   * читает 3 крутилки K1–K3 и энкодер DATA (энкодеры EC11, по прерываниям);
#   * читает фейдер и ручку громкости (АЦП);
#   * светит подсветку: 16 пэдов + 15 кнопок одной цепочкой WS2812 / SK6812;
#   * управляет питанием («защёлка», только на своей плате, см. POWER_CONTROL);
#   * говорит с Pi по UART текстом (протокол — software/sampley/controls.py).
#
# Залить: Thonny → «MicroPython (Raspberry Pi Pico)» → сохранить как main.py на Pico.
#
# Подключение (Pico):
#   GP0  UART TX → Pi GPIO15 (RX)          GP14/15  K1 A/B
#   GP1  UART RX ← Pi GPIO14 (TX)          GP16/17  K2 A/B
#   GP2…GP7   строки матрицы (выходы)      GP18/19  K3 A/B
#   GP8…GP13  столбцы матрицы (входы)      GP20/21  DATA A/B
#   GP22 данные подсветки                  GP26 (АЦП0) фейдер — средний вывод
#   GP27 (АЦП1) ручка громкости            GP28 ползунок питания (к GND = ВКЛ)
# Только на своей плате (голый RP2040, у Pico эти ноги заняты внутри):
#   GP23 HOLD — держать своё питание       GP24 включить 5 В (EN бустера)
#   GP25 «Pi выключилась» (GPIO26 Pi)
#
# Потенциометры — между 3V3(OUT)/ADC_VREF и AGND, средний вывод на АЦП.
# В матрице на каждой кнопке диод 1N4148W (катод к строке).

import machine
import neopixel
import time
from machine import ADC, Pin, UART

VERSION = "sampley-mcu 2"
# На макетке Pico питается от Pi (питание — UPS-Lite), защёлки нет.
POWER_CONTROL = False
LED_BRIGHTNESS = 0.35          # подсветка ярче — меньше работает от батареи

uart = UART(0, 115200, tx=Pin(0), rx=Pin(1))
rows = [Pin(n, Pin.OUT, value=1) for n in (2, 3, 4, 5, 6, 7)]
cols = [Pin(n, Pin.IN, Pin.PULL_UP) for n in (8, 9, 10, 11, 12, 13)]
enc_pins = [(Pin(a, Pin.IN, Pin.PULL_UP), Pin(b, Pin.IN, Pin.PULL_UP))
            for a, b in ((14, 15), (16, 17), (18, 19), (20, 21))]
pots = [ADC(26), ADC(27)]                       # 0 — фейдер, 1 — громкость
slider = Pin(28, Pin.IN, Pin.PULL_UP)

# Порядок светодиодов кнопок после 16 пэдов — как BUTTON_LEDS в controls.py.
BUTTON_LEDS = ["SHIFT", "PLAY", "STOP", "REC", "SAMPLE", "STEP", "CHOP", "MUTE",
               "MODE", "LEVELS", "BANK", "REPEAT", "TAP", "BROWSE", "KITS"]
NUM_LEDS = 16 + len(BUTTON_LEDS)
leds = neopixel.NeoPixel(Pin(22), NUM_LEDS)

if POWER_CONTROL:
    hold = Pin(23, Pin.OUT, value=1)            # первым делом — удержать своё питание
    boost_en = Pin(24, Pin.OUT, value=1)        # раз нас включили — ползунок уже «вкл»
    pi_halted = Pin(25, Pin.IN, Pin.PULL_DOWN)

# Что стоит в каждой клетке матрицы (строка, столбец).
KEYMAP = {}
for r in range(4):
    for c in range(4):
        KEYMAP[(r, c)] = ("P", r * 4 + c)
for i in range(4):
    KEYMAP[(i, 4)] = ("K", i)                   # нажатия K1, K2, K3, DATA
KEYMAP[(0, 5)] = ("B", "SHIFT")
KEYMAP[(1, 5)] = ("B", "PLAY")
KEYMAP[(2, 5)] = ("B", "STOP")
KEYMAP[(3, 5)] = ("B", "REC")
KEYMAP[(4, 0)] = ("B", "SAMPLE")
KEYMAP[(4, 1)] = ("B", "STEP")
KEYMAP[(4, 2)] = ("B", "CHOP")
KEYMAP[(4, 3)] = ("B", "MUTE")
KEYMAP[(4, 4)] = ("B", "MODE")
KEYMAP[(4, 5)] = ("B", "LEVELS")
KEYMAP[(5, 0)] = ("B", "BANK")
KEYMAP[(5, 1)] = ("B", "REPEAT")
KEYMAP[(5, 2)] = ("B", "TAP")
KEYMAP[(5, 3)] = ("B", "BROWSE")
KEYMAP[(5, 4)] = ("B", "KITS")
# (5, 5) — запас

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


pot_smooth = [p.read_u16() for p in pots]
pot_sent = [-100, -100]
pot_last_ms = 0


def scan_pots(now):
    # 100 раз в секунду, со сглаживанием; шлём, только если сдвинулось заметно
    global pot_last_ms
    if time.ticks_diff(now, pot_last_ms) < 10:
        return
    pot_last_ms = now
    for i, p in enumerate(pots):
        pot_smooth[i] += (p.read_u16() - pot_smooth[i]) // 4
        v = pot_smooth[i] >> 6                        # 0…1023
        if abs(v - pot_sent[i]) >= 4 or (v in (0, 1023) and v != pot_sent[i]):
            pot_sent[i] = v
            send("A %d %d" % (i, v))


def set_led(i, hexrgb):
    if i >= NUM_LEDS:
        return
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
            if parts[0] == "LA":
                for i, h in enumerate(parts[1:]):
                    set_led(i, h)
                dirty = True
            elif parts[0] == "?":
                send("V " + VERSION)
                send("S " + ("ON" if slider.value() == 0 else "OFF"))
                pot_sent[0] = pot_sent[1] = -100       # заново прислать фейдер и громкость
        except ValueError:
            pass
    if dirty:
        leds.write()


# --- питание (только на своей плате) -----------------------------------------
ON, STOPPING, OFF = 0, 1, 2
power = ON
stop_started = 0
STOP_TIMEOUT_MS = 30000


def power_step(now):
    # Ползунок «выкл» → сказать Pi → ждать, пока Linux остановится → снять 5 В →
    # отпустить HOLD: питание пропадает у всего, включая этот микроконтроллер.
    global power, stop_started
    if not POWER_CONTROL:
        return
    want_on = slider.value() == 0
    if power == ON and not want_on:
        send("S OFF")                                  # Pi сохранит всё и выключится
        power, stop_started = STOPPING, now
    elif power == STOPPING:
        if pi_halted.value() or time.ticks_diff(now, stop_started) > STOP_TIMEOUT_MS:
            time.sleep_ms(1500)                        # дать карте памяти дописать
            leds.fill((0, 0, 0))
            leds.write()
            boost_en.value(0)
            hold.value(0)
            power = OFF
    elif power == OFF and want_on:
        # ползунок включили обратно, пока гасли (защёлка держится через ползунок)
        hold.value(1)
        boost_en.value(1)
        power = ON


leds.fill((0, 0, 0))
leds.write()
send("V " + VERSION)
while True:
    now = time.ticks_ms()
    power_step(now)
    if power == OFF:
        time.sleep_ms(20)
        continue
    scan_keys(now)
    scan_encoders()
    scan_pots(now)
    handle_uart()
