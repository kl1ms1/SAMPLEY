"""Запуск SAMPLEY.

  python3 -m sampley            — на устройстве (Pi): экран, МК, звук
  python3 -m sampley --sim      — на компьютере: окно + клавиатура (нужен pygame)
  python3 -m sampley --demo DIR — без экрана и звука: сыграть демо-бит в WAV
                                  и сохранить картинки всех экранов (проверка)
"""

from __future__ import annotations

import os
import sys
import time

from .app import App, Screen
from .board import detect
from .controls import (FADER, KEY_BUTTONS, KEY_JOG_TOUCH, KEY_JOGS, KEY_ENC_PUSH, KEY_ENCODERS, KEY_FADER, KEY_PADS, Button, Event,
                       Kind)
from .engine import Engine
from .kit import load_default, load_kit, list_kits, KITS_DIR
from . import ui


def make_engine(profile) -> Engine:
    eng = Engine(max_voices=profile.voices, block=profile.block)
    if "autosave" in list_kits():
        try:
            load_kit(eng, "autosave")
            return eng
        except Exception as exc:                      # битый автосейв не должен мешать запуску
            print(f"[кит] автосейв не загрузился: {exc}")
    load_default(eng)
    return eng


# --- демо без железа ----------------------------------------------------------
def demo(out_dir: str) -> int:
    import numpy as np
    from .sample import Sample, save_wav

    os.makedirs(out_dir, exist_ok=True)
    profile, _ = detect()
    eng = Engine(max_voices=profile.voices, block=profile.block)
    load_default(eng)
    app = App(eng, kits_root=os.path.join(out_dir, "kits"))
    app.battery, app.charging = 76, True

    eng.seq.start()
    blocks = []
    total = int(44100 * 60 / eng.seq.bpm * 4 * 4)           # 4 такта
    done = 0
    while done < total:
        blocks.append(eng.render(eng.block))
        done += eng.block
        if done > total // 2 and not eng.seq.queued:
            eng.note_on(12)                                  # аккорд поверх бита
            eng.seq.queued = 0
    save_wav(Sample("demo", np.concatenate(blocks)), os.path.join(out_dir, "demo.wav"))

    shots = {}
    eng.render(eng.block)
    app.selected = 0
    shots["play"] = ui.render(app)
    app.handle(Event(Kind.BUTTON, value=1, button=Button.SHIFT))
    shots["shift"] = ui.render(app)
    app.handle(Event(Kind.BUTTON, value=0, button=Button.SHIFT))
    app.handle(Event(Kind.BUTTON, value=1, button=Button.STEP))
    shots["step"] = ui.render(app)
    app.go(Screen.PLAY)
    eng.seq.stop()
    app.handle(Event(Kind.BUTTON, value=1, button=Button.SAMPLE))
    eng.recorder.level = 0.35
    shots["sample"] = ui.render(app)
    app.go(Screen.PLAY)
    # «запись с улицы»: склеим несколько ударов в один звук и порежем его
    from .kit_synth import clap, kick, snare, tom
    phrase = np.concatenate([kick()[:9000], snare()[:7000], tom(160)[:8000], clap()[:6000],
                             kick()[:5000], tom(110)[:9000]])
    app.selected = 16                                         # пэд B1
    eng.pads[16].sample = Sample.from_mono("Улица 1", phrase).normalized(0.8)
    app.bank = 1
    app.handle(Event(Kind.BUTTON, value=1, button=Button.CHOP))
    app.chopper.cursor = 2
    shots["chop"] = ui.render(app)
    app.handle(Event(Kind.ENC_PUSH, 0, 1))
    app.toast = ""
    shots["bank_b"] = ui.render(app)
    app.bank = 0
    app.handle(Event(Kind.BUTTON, value=1, button=Button.KITS))
    shots["kits"] = ui.render(app)
    for name, img in shots.items():
        img.resize((640, 480)).save(os.path.join(out_dir, f"screen_{name}.png"))
    print(f"Готово: {out_dir}/demo.wav и screen_*.png")
    return 0


# --- симуляция на компьютере --------------------------------------------------
def sim() -> int:
    try:
        import pygame  # type: ignore
    except ImportError:
        print("Для окна нужен pygame:  pip install pygame sounddevice")
        return 1
    profile, _ = detect()
    eng = make_engine(profile)
    app = App(eng)
    app.battery = 100
    audio = None
    try:
        from .hw import Audio
        audio = Audio(eng, profile.block)
    except Exception as exc:
        print(f"[звук] недоступен ({exc}) — будет тихо")

    pygame.init()
    scale = 2
    win = pygame.display.set_mode((ui.W * scale, ui.H * scale + 98))
    pygame.display.set_caption("SAMPLEY — симуляция")
    hint = pygame.font.SysFont(None, 20)
    lines = ["Пэды 1234/qwer/asdf/zxcv · K1 5-6 (или колесо мыши), K2 t-y, K3 g-h · нажать 7 u j",
             "Shift SHIFT · Пробел PLAY · Backspace STOP · Enter REC · Tab REPEAT · B STUTTER · [ ] фейдер",
             "Вертушки: левая o p (палец — держи 9) · правая k l (палец — 0)",
             "F1 SAMPLE F2 STEP F3 CHOP F4 MUTE F5 MODE F6 LEVELS F7 BANK F8 TAP F9 BROWSE F10 KITS · Esc выход"]

    def key_name(k):
        n = pygame.key.name(k)
        return "shift" if "shift" in n else n

    clock = pygame.time.Clock()
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type in (pygame.KEYDOWN, pygame.KEYUP):
                down = 1 if e.type == pygame.KEYDOWN else 0
                k = key_name(e.key)
                if k == "escape":
                    running = False
                elif k in KEY_PADS:
                    app.handle(Event(Kind.PAD, KEY_PADS.index(k), down))
                elif k in KEY_BUTTONS:
                    app.handle(Event(Kind.BUTTON, value=down, button=KEY_BUTTONS[k]))
                elif k in KEY_ENC_PUSH:
                    app.handle(Event(Kind.ENC_PUSH, KEY_ENC_PUSH.index(k), down))
                elif k in KEY_JOG_TOUCH:
                    app.handle(Event(Kind.JOG_TOUCH, KEY_JOG_TOUCH[k], down))
                elif down and k in KEY_JOGS:
                    wheel, counts = KEY_JOGS[k]
                    app.handle(Event(Kind.JOG, wheel, counts))
                elif down and k in KEY_FADER:
                    v = app.fader + (0.05 if k == KEY_FADER[1] else -0.05)
                    app.handle(Event(Kind.ANALOG, FADER, round(max(0.0, min(1.0, v)) * 1023)))
                elif down:
                    for i, (dec, inc) in enumerate(KEY_ENCODERS):
                        if k in (dec, inc):
                            app.handle(Event(Kind.ENCODER, i, -1 if k == dec else 1))
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 2:
                app.handle(Event(Kind.ENC_PUSH, 0, 1))
            elif e.type == pygame.MOUSEWHEEL:
                app.handle(Event(Kind.ENCODER, 0, e.y))
        app.tick()
        img = ui.render(app)
        surf = pygame.image.fromstring(img.tobytes(), img.size, "RGB")
        win.fill((0, 0, 0))
        win.blit(pygame.transform.scale(surf, (ui.W * scale, ui.H * scale)), (0, 0))
        for i, t in enumerate(lines):
            win.blit(hint.render(t, True, (180, 180, 180)), (8, ui.H * scale + 6 + i * 22))
        pygame.display.flip()
        clock.tick(30)
    if audio:
        audio.close()
    pygame.quit()
    return 0


# --- устройство -----------------------------------------------------------------
def device() -> int:
    from . import hw
    profile, model = detect()
    print(f"SAMPLEY: {model.strip(chr(0)) if model else profile.name}; "
          f"{profile.voices} голосов, задержка ≈{profile.latency_ms:.0f} мс")
    eng = make_engine(profile)
    app = App(eng, on_shutdown=hw.poweroff)

    def optional(what, make):
        try:
            return make()
        except Exception as exc:
            print(f"[{what}] не найден: {exc.__class__.__name__}: {exc}")
            return None

    display = optional("экран", lambda: hw.ST7789(profile.spi_hz)) or hw.PNGDisplay("/tmp/sampley.png")
    mcu = optional("МК", hw.McuLink)
    battery = optional("батарея", hw.Battery)
    if battery:
        battery.setup_care_charging(True)
    audio = optional("звук", lambda: hw.Audio(eng, profile.block))

    frame = 1.0 / profile.ui_fps
    last_batt = 0.0
    last_light = None
    try:
        while True:
            t0 = time.monotonic()
            if mcu:
                while not mcu.events.empty():
                    app.handle(mcu.events.get())
            if battery and t0 - last_batt > 5:
                from .power import Action, check
                st = battery.state()
                app.battery, app.charging = st.percent, st.charging
                last_batt = t0
                act = check(st)
                if act in (Action.SHUTDOWN_EMPTY, Action.SHUTDOWN_HOT):
                    app.say(act.value, 5)
                    app.shutdown()
                elif act is not Action.OK:
                    app.say(f"Аккумулятор: {act.value}", 3)
            app.tick()
            if app.dirty:
                display.show(ui.render(app))
                app.dirty = False
            if mcu:
                mcu.set_leds(app.led_colors())
                if app.light_mode != last_light:
                    mcu.send(f"LM {app.light_mode}\n")
                    last_light = app.light_mode
                for pad, vel in app.take_hits():                  # удары секвенсора — в эффекты подсветки
                    mcu.send(f"H {pad} {vel}\n")
            time.sleep(max(0.0, frame - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if audio:
            audio.close()
    return 0


def main(argv: list[str]) -> int:
    if "--demo" in argv:
        i = argv.index("--demo")
        return demo(argv[i + 1] if len(argv) > i + 1 else "out")
    if "--sim" in argv:
        return sim()
    return device()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
