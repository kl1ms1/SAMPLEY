"""Отрисовка экрана 320×240 (2.0″ IPS, ST7789) через Pillow.

Одна и та же картинка уходит и на настоящий экран (по SPI), и в окно /
PNG-файл в симуляции.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .app import ROW_COLORS, App, Screen
from .recorder import RecState
from .sequencer import PADS

W, H = 320, 240
BG = (12, 12, 16)
FG = (230, 230, 235)
DIM = (110, 110, 120)
ACCENT = (255, 140, 0)
RED = (255, 50, 50)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _font(size: int):
    for p in _FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_S, F_M, F_L = _font(11), _font(14), _font(20)


def _fit(d: ImageDraw.ImageDraw, text: str, width: int, font=F_S) -> str:
    """Укоротить подпись, чтобы влезла в клетку пэда."""
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _bar(d: ImageDraw.ImageDraw, x, y, w, h, frac, color):
    d.rectangle([x, y, x + w, y + h], outline=DIM)
    d.rectangle([x + 1, y + 1, x + 1 + int((w - 2) * max(0, min(1, frac))), y + h - 1], fill=color)


def _wave(d: ImageDraw.ImageDraw, sample, x, y, w, h, start=0.0, end=1.0, color=FG):
    if sample is None:
        d.text((x + w // 2, y + h // 2), "пусто", font=F_M, fill=DIM, anchor="mm")
        return
    peaks = sample.overview(w)
    mid = y + h // 2
    a, b = int(start * w), int(end * w)
    for i, pk in enumerate(peaks):
        k = int(pk * h / 2)
        d.line([x + i, mid - k, x + i, mid + k], fill=color if a <= i <= b else DIM)
    d.line([x + a, y, x + a, y + h], fill=ACCENT)
    d.line([x + b, y, x + b, y + h], fill=ACCENT)


def _header(d: ImageDraw.ImageDraw, app: App):
    seq = app.engine.seq
    d.rectangle([0, 0, W, 20], fill=(28, 28, 36))
    d.text((6, 3), app.screen.value, font=F_M, fill=ACCENT)
    state = "▶" if seq.playing else "■"
    if seq.recording:
        state = "●"
    d.text((70, 3), f"{state} {seq.bpm:g} BPM  P{seq.current + 1}", font=F_M,
           fill=RED if seq.recording else FG)
    if app.battery is not None:
        bx = W - 40
        col = (80, 220, 80) if app.battery > 20 else RED
        d.rectangle([bx, 5, bx + 26, 15], outline=FG)
        d.rectangle([bx + 27, 8, bx + 29, 12], fill=FG)
        d.rectangle([bx + 2, 7, bx + 2 + int(22 * app.battery / 100), 13], fill=col)
        if app.charging:
            d.text((bx - 10, 3), "⚡", font=F_M, fill=ACCENT)
    if app.shift:
        d.text((W - 80, 4), "SHIFT", font=F_S, fill=ACCENT)


def _footer(d: ImageDraw.ImageDraw, app: App):
    y = H - 34
    d.line([0, y - 2, W, y - 2], fill=(40, 40, 50))
    for i, (label, value) in enumerate(app.encoder_labels()):
        x = i * W // 4 + W // 8
        d.text((x, y + 2), label, font=F_S, fill=DIM, anchor="mt")
        d.text((x, y + 15), value, font=F_M, fill=FG, anchor="mt")


def _pad_grid(d: ImageDraw.ImageDraw, app: App, x0, y0, cell_w, cell_h):
    eng = app.engine
    for i in range(PADS):
        r, c = divmod(i, 4)
        x, y = x0 + c * cell_w, y0 + r * cell_h
        pad = eng.pads[i]
        if app.screen is Screen.STEP:
            on = eng.seq.pattern.grid[app.selected][i]
            fill = ROW_COLORS[app.selected // 4] if on else (30, 30, 38)
            if eng.seq.playing and eng.seq.step == i:
                fill = (255, 255, 255) if on else (70, 70, 80)
            d.rounded_rectangle([x + 2, y + 2, x + cell_w - 3, y + cell_h - 3], 4, fill=fill)
            d.text((x + cell_w // 2, y + cell_h // 2), str(i + 1), font=F_S,
                   fill=BG if on else DIM, anchor="mm")
            continue
        playing = i in eng.playing_pads
        base = ROW_COLORS[r]
        fill = (255, 255, 255) if playing else (30, 30, 38)
        d.rounded_rectangle([x + 2, y + 2, x + cell_w - 3, y + cell_h - 3], 4, fill=fill,
                            outline=base if i == app.selected else None, width=2)
        name = _fit(d, pad.name, cell_w - 8)
        color = BG if playing else (DIM if pad.mute or pad.sample is None else FG)
        d.text((x + cell_w // 2, y + cell_h // 2), name, font=F_S, fill=color, anchor="mm")


def render(app: App) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _header(d, app)
    eng, pad = app.engine, app.pad

    if app.screen in (Screen.PLAY, Screen.STEP):
        # слева — сетка пэдов, справа — выбранный пэд
        _pad_grid(d, app, 4, 24, 46, 44)
        x = 194
        d.text((x, 26), f"Пэд {app.selected + 1}", font=F_S, fill=DIM)
        d.text((x, 38), pad.name[:12], font=F_L, fill=FG)
        _wave(d, pad.sample, x, 66, 120, 50, pad.start, pad.end, ROW_COLORS[app.selected // 4])
        flags = [pad.mode.value]
        if pad.reverse:
            flags.append("назад")
        if pad.mute:
            flags.append("тихо")
        if pad.choke:
            flags.append(f"глуш {pad.choke}")
        d.text((x, 122), " · ".join(flags), font=F_S, fill=DIM)
        if app.screen is Screen.STEP:
            d.text((x, 140), "Пэды = шаги", font=F_S, fill=ACCENT)
            d.text((x, 154), "SHIFT+пэд — выбор", font=F_S, fill=DIM)
        else:
            d.text((x, 140), "Уровень", font=F_S, fill=DIM)
            _bar(d, x, 155, 120, 8, eng.level, (80, 220, 80) if eng.level < 0.9 else RED)
        if eng.seq.playing:
            for s in range(16):
                sx = x + s * 7.5
                d.rectangle([sx, 172, sx + 5, 178], fill=ACCENT if s == eng.seq.step else (50, 50, 60))

    elif app.screen is Screen.SAMPLE:
        rec = eng.recorder
        d.text((W // 2, 40), f"Запись на пэд {app.selected + 1}", font=F_L, fill=FG, anchor="mm")
        status = {RecState.ARMED: "Жду звук… (энкодер 1 — сразу)", RecState.RECORDING: "● ИДЁТ ЗАПИСЬ",
                  RecState.IDLE: "", RecState.DONE: "Готово"}[rec.state]
        d.text((W // 2, 70), status, font=F_M, fill=RED if rec.state is RecState.RECORDING else ACCENT,
               anchor="mm")
        d.text((W // 2, 92), f"{rec.seconds:4.1f} с", font=F_L, fill=FG, anchor="mm")
        d.text((20, 116), "Вход", font=F_S, fill=DIM)
        _bar(d, 20, 132, 280, 14, rec.level, (80, 220, 80) if rec.level < 0.9 else RED)
        tx = 21 + int(278 * rec.threshold)
        d.line([tx, 128, tx, 150], fill=ACCENT)
        d.text((20, 160), "REC — стоп / отмена", font=F_S, fill=DIM)

    elif app.screen is Screen.KITS:
        items = app.kit_items()
        top = max(0, min(app.kit_cursor - 4, len(items) - 9))
        for row, name in enumerate(items[top:top + 9]):
            i = top + row
            y = 26 + row * 19
            if i == app.kit_cursor:
                d.rectangle([4, y - 1, W - 4, y + 16], fill=(40, 40, 55))
            d.text((10, y), name, font=F_M, fill=ACCENT if i < 2 else FG)
        d.text((W - 8, 26), f"сейчас: {app.kit_name}", font=F_S, fill=DIM, anchor="ra")

    if app.toast:
        tw = d.textlength(app.toast, font=F_M)
        d.rounded_rectangle([W / 2 - tw / 2 - 10, 92, W / 2 + tw / 2 + 10, 122], 6, fill=(0, 0, 0),
                            outline=ACCENT)
        d.text((W // 2, 107), app.toast, font=F_M, fill=FG, anchor="mm")
    _footer(d, app)
    return img


def to_rgb565(img: Image.Image) -> bytes:
    """Картинка → байты для ST7789 (16 бит на точку, старший байт первым)."""
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
    return v.astype(">u2").tobytes()
