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
from .controls import KEY_BUTTONS, KEY_ENC_PUSH, KEY_ENCODERS, KEY_PADS, Button, Event, Kind
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
    app.handle(Event(Kind.BUTTON, value=1, button=Button.PLAY))
    app.handle(Event(Kind.BUTTON, value=0, button=Button.SHIFT))
    shots["step"] = ui.render(app)
    app.screen = Screen.PLAY
    eng.seq.stop()
    app.handle(Event(Kind.BUTTON, value=1, button=Button.REC))
    eng.recorder.level = 0.35
    shots["sample"] = ui.render(app)
    app.screen = Screen.KITS
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
    win = pygame.display.set_mode((ui.W * scale, ui.H * scale + 60))
    pygame.display.set_caption("SAMPLEY — симуляция")
    hint = pygame.font.SysFont(None, 20)
    lines = ["Пэды: 1234 / qwer / asdf / zxcv    Энкодеры: 5-6  t-y  g-h  b-n (нажатие: 7 u j m)",
             "Shift — SHIFT,  Пробел — PLAY,  Enter — REC,  колесо мыши — энкодер 1,  Esc — выход"]

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
                elif down:
                    for i, (dec, inc) in enumerate(KEY_ENCODERS):
                        if k in (dec, inc):
                            app.handle(Event(Kind.ENCODER, i, -1 if k == dec else 1))
            elif e.type == pygame.MOUSEWHEEL:
                app.handle(Event(Kind.ENCODER, 0, e.y))
        app.tick()
        img = ui.render(app)
        surf = pygame.image.fromstring(img.tobytes(), img.size, "RGB")
        win.fill((0, 0, 0))
        win.blit(pygame.transform.scale(surf, (ui.W * scale, ui.H * scale)), (0, 0))
        for i, t in enumerate(lines):
            win.blit(hint.render(t, True, (180, 180, 180)), (8, ui.H * scale + 8 + i * 22))
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
    audio = optional("звук", lambda: hw.Audio(eng, profile.block))

    frame = 1.0 / profile.ui_fps
    last_batt = 0.0
    try:
        while True:
            t0 = time.monotonic()
            if mcu:
                while not mcu.events.empty():
                    app.handle(mcu.events.get())
            if battery and t0 - last_batt > 5:
                app.battery, app.charging = battery.percent(), battery.charging()
                last_batt = t0
                if app.battery is not None and app.battery <= 3 and not app.charging:
                    app.say("Батарея села")
                    app.shutdown()
            app.tick()
            if app.dirty:
                display.show(ui.render(app))
                app.dirty = False
            if mcu:
                mcu.set_leds(app.pad_colors())
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
