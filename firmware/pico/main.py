# SAMPLEY — прошивка микроконтроллера управления (MicroPython, Raspberry Pi Pico / RP2040).
#
# Что делает:
#   * 16 пэдов С СИЛОЙ УДАРА: под каждым — датчик давления (на своей плате —
#     токопроводящая таблетка силиконового пэда на «гребёнке», на макетке — FSR402).
#     Все 16 — через мультиплексор 74HC4067 в один АЦП, опрос ≈1000 раз/с;
#   * 16 кнопок + 4 нажатия энкодеров — через 3 сдвиговых регистра 74HC165
#     (всего 3 ноги на все кнопки);
#   * 3 крутилки K1–K3 и колёсико DATA на боку — энкодеры БЕЗ щелчков, по прерываниям;
#   * 2 вертушки (диски-«пластинки») — под каждой магнитный датчик угла AS5600
#     (4096 точек на оборот, свой I2C у каждой), сверху сенсор касания;
#   * фейдер и колёсико громкости на боку — АЦП;
#   * подсветка: 16 пэдов + 16 кнопок одной цепочкой WS2812 / SK6812;
#   * питание («защёлка») — только на своей плате, см. POWER_CONTROL;
#   * говорит с Pi по UART текстом (протокол — software/sampley/controls.py).
#
# Залить: Thonny → «MicroPython (Raspberry Pi Pico)» → сохранить как main.py на Pico.
#
# Подключение (Pico):
#   GP0  UART TX → Pi GPIO15 (RX)          GP9/10   K1 A/B
#   GP1  UART RX ← Pi GPIO14 (TX)          GP11/12  K2 A/B
#   GP2…GP5  S0…S3 мультиплексора пэдов    GP13/14  K3 A/B
#   GP28 (АЦП2) SIG мультиплексора пэдов   GP15/16  DATA A/B (колёсико на правом боку)
#   GP6  74HC165 SH/LD (защёлкнуть)        GP17     данные подсветки
#   GP7  74HC165 CLK                       GP18/19  I2C1 SDA/SCL — AS5600 левой вертушки
#   GP8  74HC165 QH (данные)               GP20/21  I2C0 SDA/SCL — AS5600 правой вертушки
#   GP26 (АЦП0) фейдер                     GP27 (АЦП1) громкость (колёсико на левом боку)
#   GP22 ползунок питания (к GND = ВКЛ)
# Сенсоры касания вертушек (TTP223, выход «0» при касании) — на свободные входы 74HC165.
# Только на своей плате (голый RP2040, у Pico эти ноги заняты внутри):
#   GP23 HOLD — держать своё питание       GP24 включить 5 В (EN бустера)
#   GP25 «Pi выключилась» (GPIO26 Pi)
#
# Датчик пэда: между 3V3 и каналом мультиплексора, канал — к GND через 10 кОм.
# Нажал сильнее → сопротивление меньше → напряжение выше.
# Кнопки на входах 74HC165 — к GND, подтяжка 10 кОм к 3V3 (сборки резисторов).

import machine
import neopixel
import time
from machine import ADC, Pin, UART

VERSION = "sampley-mcu 3"
POWER_CONTROL = False          # на макетке питание — UPS-Lite, защёлки нет
LED_BRIGHTNESS = 0.35          # подсветка ярче — меньше работает от батареи

# --- калибровка пэдов (подстроить на макетке: печатает DEBUG_PADS) ---------------
PAD_ON = 3500                  # выше — пэд нажат (из 65535)
PAD_OFF = 2000                 # ниже — отпущен (гистерезис, без дребезга)
PAD_FULL = 52000               # «со всей силы»
VEL_WINDOW_US = 3000           # силу удара меряем по пику за первые 3 мс
VEL_CURVE = 0.6                # <1 — легче получить громкий удар
DEBUG_PADS = False

ENC_DIV = 2                    # энкодеры без щелчков: событие на каждые 2 перехода — плавно и точно
JOG_FLIP = (1, 1)              # знак поворота левой / правой вертушки (как стоит магнит)

uart = UART(0, 115200, tx=Pin(0), rx=Pin(1))

# --- пэды: мультиплексор + АЦП ---------------------------------------------------
for n in (2, 3, 4, 5):
    Pin(n, Pin.OUT, value=0)
pad_adc = ADC(28)
SIO_OUT_SET, SIO_OUT_CLR = 0xD0000014, 0xD0000018
MUX_MASK = 0b1111 << 2
pad_state = [0] * 16           # 0 — отпущен, 1 — меряем силу, 2 — нажат
pad_t0 = [0] * 16
pad_peak = [0] * 16


def scan_pads():
    for ch in range(16):
        machine.mem32[SIO_OUT_CLR] = MUX_MASK
        machine.mem32[SIO_OUT_SET] = ch << 2
        time.sleep_us(2)                               # дать мультиплексору установиться
        v = pad_adc.read_u16()
        st = pad_state[ch]
        if st == 0:
            if v > PAD_ON:
                pad_state[ch], pad_t0[ch], pad_peak[ch] = 1, time.ticks_us(), v
        elif st == 1:
            if v > pad_peak[ch]:
                pad_peak[ch] = v
            if time.ticks_diff(time.ticks_us(), pad_t0[ch]) >= VEL_WINDOW_US:
                x = (pad_peak[ch] - PAD_ON) / (PAD_FULL - PAD_ON)
                x = 0.0 if x < 0 else (1.0 if x > 1 else x)
                vel = 1 + int(126 * x ** VEL_CURVE)
                pad_state[ch] = 2
                send("P %d 1 %d" % (ch, vel))
                if DEBUG_PADS:
                    print("pad", ch, "peak", pad_peak[ch], "vel", vel)
        elif v < PAD_OFF:
            pad_state[ch] = 0
            send("P %d 0" % ch)


# --- кнопки: 3 × 74HC165 -----------------------------------------------------------
sr_load = Pin(6, Pin.OUT, value=1)
sr_clk = Pin(7, Pin.OUT, value=0)
sr_data = Pin(8, Pin.IN)
# Что на каком входе цепочки (первый — D7 первого регистра). None — свободно.
BUTTON_INPUTS = [
    "SHIFT", "PLAY", "STOP", "REC", "SAMPLE", "STEP", "CHOP", "MUTE",
    "MODE", "LEVELS", "BANK", "REPEAT", "TAP", "BROWSE", "KITS", "STUTTER",
    "K0", "K1", "K2", "K3", "JT0", "JT1", None, None,
]
btn_state = [False] * len(BUTTON_INPUTS)
btn_changed = [0] * len(BUTTON_INPUTS)
DEBOUNCE_MS = 5


def scan_buttons(now):
    sr_load.value(0)                                   # защёлкнуть все входы разом
    sr_load.value(1)
    for i, name in enumerate(BUTTON_INPUTS):
        down = sr_data.value() == 0
        sr_clk.value(1)
        sr_clk.value(0)
        if name is None or down == btn_state[i] or time.ticks_diff(now, btn_changed[i]) < DEBOUNCE_MS:
            continue
        btn_state[i], btn_changed[i] = down, now
        if name[0] == "K":
            send("K %s %d" % (name[1], 1 if down else 0))
        elif name.startswith("JT"):
            send("JT %s %d" % (name[2], 1 if down else 0))
        else:
            send("B %s %d" % (name, 1 if down else 0))


# --- энкодеры без щелчков ------------------------------------------------------------
enc_pins = [(Pin(a, Pin.IN, Pin.PULL_UP), Pin(b, Pin.IN, Pin.PULL_UP))
            for a, b in ((9, 10), (11, 12), (13, 14), (15, 16))]
QDEC = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)
enc_prev = [(a.value() << 1) | b.value() for a, b in enc_pins]
enc_acc = [0, 0, 0, 0]


def _enc_irq(_pin):
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
        if abs(acc) >= ENC_DIV:
            clicks = int(acc / ENC_DIV)
            irq = machine.disable_irq()
            enc_acc[i] -= clicks * ENC_DIV
            machine.enable_irq(irq)
            send("E %d %d" % (i, clicks))


# --- вертушки: AS5600 (угол 0…4095), у каждой свой I2C — адрес у датчика один (0x36) ----
jog_i2c = [machine.I2C(1, sda=Pin(18), scl=Pin(19), freq=400_000),
           machine.I2C(0, sda=Pin(20), scl=Pin(21), freq=400_000)]
AS5600, RAW_ANGLE = 0x36, 0x0C
jog_prev = [None, None]
jog_acc = [0, 0]
jog_last_poll = 0
jog_last_send = 0


def _angle(i):
    hi, lo = jog_i2c[i].readfrom_mem(AS5600, RAW_ANGLE, 2)
    return ((hi & 0x0F) << 8) | lo


def scan_jogs(now):
    global jog_last_poll, jog_last_send
    if time.ticks_diff(now, jog_last_poll) < 2:        # 500 раз/с — успеваем даже за быстрым скретчем
        return
    jog_last_poll = now
    for i in (0, 1):
        try:
            a = _angle(i)
        except OSError:
            continue                                   # вертушка не подключена — не мешает остальному
        if jog_prev[i] is not None:
            d = a - jog_prev[i]
            if d > 2048:                               # перешли через ноль
                d -= 4096
            elif d < -2048:
                d += 4096
            jog_acc[i] += d * JOG_FLIP[i]
        jog_prev[i] = a
    if time.ticks_diff(now, jog_last_send) >= 8:       # ≈120 сообщений/с — плавно и не забивает UART
        jog_last_send = now
        for i in (0, 1):
            if jog_acc[i]:
                send("J %d %d" % (i, jog_acc[i]))
                jog_acc[i] = 0


# --- фейдер и колёсико громкости ------------------------------------------------------
pots = [ADC(26), ADC(27)]
pot_smooth = [p.read_u16() for p in pots]
pot_sent = [-100, -100]
pot_last_ms = 0


def scan_pots(now):
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


# --- подсветка ---------------------------------------------------------------------------
# Порядок светодиодов кнопок после 16 пэдов — как BUTTON_LEDS в controls.py.
BUTTON_LEDS = ["SHIFT", "PLAY", "STOP", "REC", "SAMPLE", "STEP", "CHOP", "MUTE",
               "MODE", "LEVELS", "BANK", "REPEAT", "TAP", "BROWSE", "KITS", "STUTTER"]
NUM_LEDS = 16 + len(BUTTON_LEDS)
leds = neopixel.NeoPixel(Pin(17), NUM_LEDS)


def set_led(i, hexrgb):
    if i >= NUM_LEDS:
        return
    v = int(hexrgb, 16)
    k = LED_BRIGHTNESS
    leds[i] = (int(((v >> 16) & 255) * k), int(((v >> 8) & 255) * k), int((v & 255) * k))


# --- связь с Pi ----------------------------------------------------------------------------
def send(line):
    uart.write(line + "\n")


rx = b""
slider = Pin(22, Pin.IN, Pin.PULL_UP)


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


# --- питание (только на своей плате) -------------------------------------------------------
if POWER_CONTROL:
    hold = Pin(23, Pin.OUT, value=1)            # первым делом — удержать своё питание
    boost_en = Pin(24, Pin.OUT, value=1)        # раз нас включили — ползунок уже «вкл»
    pi_halted = Pin(25, Pin.IN, Pin.PULL_DOWN)
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
        send("S OFF")
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
    scan_pads()
    scan_buttons(now)
    scan_encoders()
    scan_jogs(now)
    scan_pots(now)
    handle_uart()
