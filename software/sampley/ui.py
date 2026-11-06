"""Отрисовка экрана 320×240 (2.0″ IPS, ST7789) через Pillow.

Одна и та же картинка уходит и на настоящий экран (по SPI), и в окно /
PNG-файл в симуляции.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .app import BANK_COLORS, BANK_NAMES, ROW_COLORS, App, Screen, level_semis
from .recorder import RecState
from .sequencer import BANK_SIZE

W, H = 320, 240
BG = (12, 12, 16)
FG = (230, 230, 235)
DIM = (110, 110, 120)
ACCENT = (255, 140, 0)
RED = (255, 50, 50)
GREEN = (80, 220, 80)
CELL = (30, 30, 38)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _font(size: int):
    for p in _FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_XS, F_S, F_M, F_L = _font(10), _font(11), _font(14), _font(20)


def _fit(d: ImageDraw.ImageDraw, text: str, width: int, font=F_S) -> str:
    """Укоротить подпись, чтобы влезла."""
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _pad_text(d: ImageDraw.ImageDraw, text: str, cx: int, cy: int, width: int, fill):
    """Подпись пэда: одна строка, если влезает, иначе две помельче."""
    if d.textlength(text, font=F_S) <= width:
        d.text((cx, cy), text, font=F_S, fill=fill, anchor="mm")
        return
    words = text.replace("·", "· ").split()
    if len(words) == 1 and d.textlength(text, font=F_XS) <= width:
        d.text((cx, cy), text, font=F_XS, fill=fill, anchor="mm")
        return
    if len(words) > 1:
        cut = max(range(1, len(words)), key=lambda k: -abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
        a, b = " ".join(words[:cut]), " ".join(words[cut:])
    else:
        half = (len(text) + 1) // 2
        a, b = text[:half], text[half:]
    d.text((cx, cy - 6), _fit(d, a.replace("· ", "·"), width, F_XS), font=F_XS, fill=fill, anchor="mm")
    d.text((cx, cy + 6), _fit(d, b.replace("· ", "·"), width, F_XS), font=F_XS, fill=fill, anchor="mm")


def _bar(d: ImageDraw.ImageDraw, x, y, w, h, frac, color):
    d.rectangle([x, y, x + w, y + h], outline=DIM)
    d.rectangle([x + 1, y + 1, x + 1 + int((w - 2) * max(0, min(1, frac))), y + h - 1], fill=color)


def _wave(d: ImageDraw.ImageDraw, sample, x, y, w, h, start=0.0, end=1.0, color=FG, marks=True):
    if sample is None:
        d.text((x + w // 2, y + h // 2), "пусто", font=F_M, fill=DIM, anchor="mm")
        return
    peaks = sample.overview(w)
    mid = y + h // 2
    a, b = int(start * w), int(end * w)
    for i, pk in enumerate(peaks):
        k = int(pk * h / 2)
        d.line([x + i, mid - k, x + i, mid + k], fill=color if a <= i <= b else (55, 55, 62))
    if marks:
        d.line([x + a, y, x + a, y + h], fill=ACCENT)
        d.line([x + min(b, w - 1), y, x + min(b, w - 1), y + h], fill=ACCENT)


def _header(d: ImageDraw.ImageDraw, app: App):
    seq, eng = app.engine.seq, app.engine
    d.rectangle([0, 0, W, 20], fill=(28, 28, 36))
    d.text((6, 3), app.screen.value, font=F_M, fill=ACCENT)
    x = 6 + d.textlength(app.screen.value, font=F_M) + 8
    state = "●" if seq.recording else ("▶" if seq.playing else "■")
    txt = f"{state} {seq.bpm:g}  P{seq.current + 1}"
    d.text((x, 3), txt, font=F_M, fill=RED if seq.recording else FG)
    x += d.textlength(txt, font=F_M) + 8
    bank_c = BANK_COLORS[app.bank]
    d.rounded_rectangle([x, 3, x + 16, 17], 3, fill=bank_c)
    d.text((x + 8, 10), BANK_NAMES[app.bank], font=F_S, fill=BG, anchor="mm")
    x += 22
    tags = []
    if app.mute_mode:
        tags.append("MUTE")
    if app.levels_mode:
        tags.append("16LV")
    if app.repeat_held:
        tags.append(f"↻{eng.repeat_rate}")
    if eng.tune:
        tags.append(f"{eng.tune:+g}♪")
    if abs(eng.filter) >= 0.03:
        tags.append("ФНЧ" if eng.filter < 0 else "ФВЧ")
    if eng.scratching:
        tags.append("◐SCR")
    if app.stutter_active:
        tags.append(f"STUT {eng.stutter_div}")
    if app.shift:
        tags.append("SHIFT")
    d.text((x, 4), " ".join(tags), font=F_S, fill=ACCENT)
    if app.battery is not None:
        bx = W - 32
        col = GREEN if app.battery > 20 else RED
        d.rectangle([bx, 5, bx + 24, 15], outline=FG)
        d.rectangle([bx + 25, 8, bx + 27, 12], fill=FG)
        d.rectangle([bx + 2, 7, bx + 2 + int(20 * app.battery / 100), 13], fill=col)
        if app.charging:
            d.text((bx + 12, 10), "⚡", font=F_S, fill=BG, anchor="mm")


def _footer(d: ImageDraw.ImageDraw, app: App):
    y = H - 34
    d.line([0, y - 2, W, y - 2], fill=(40, 40, 50))
    names = ["K1", "K2", "K3", "◑"]
    for i, (label, value) in enumerate(app.encoder_labels()):
        x = i * W // 4 + W // 8
        if label:
            d.text((x, y + 2), f"{names[i]} {label}", font=F_S, fill=DIM, anchor="mt")
        d.text((x, y + 15), value, font=F_M, fill=FG, anchor="mt")


def _pad_grid(d: ImageDraw.ImageDraw, app: App, x0, y0, cw, chh):
    eng = app.engine
    for i in range(BANK_SIZE):
        r, c = divmod(i, 4)
        x, y = x0 + c * cw, y0 + r * chh
        box = [x + 2, y + 2, x + cw - 3, y + chh - 3]
        a = app.abs_pad(i)
        pad = eng.pads[a]
        if app.screen is Screen.STEP:
            on = eng.seq.pattern.grid[app.selected][i]
            fill = ROW_COLORS[(app.selected % BANK_SIZE) // 4] if on else CELL
            if eng.seq.playing and eng.seq.step == i:
                fill = (255, 255, 255) if on else (70, 70, 80)
            d.rounded_rectangle(box, 4, fill=fill)
            d.text((x + cw // 2, y + chh // 2), str(i + 1), font=F_S, fill=BG if on else DIM, anchor="mm")
            continue
        if app.levels_mode:
            k = level_semis(i)
            d.rounded_rectangle(box, 4, fill=CELL, outline=ROW_COLORS[(app.selected % BANK_SIZE) // 4] if k == 0
                                else None, width=2)
            d.text((x + cw // 2, y + chh // 2), f"+{k}", font=F_M, fill=FG, anchor="mm")
            continue
        playing = a in eng.playing_pads
        if app.mute_mode and pad.sample is not None:
            fill = (90, 20, 20) if pad.mute else (20, 70, 35)
        else:
            fill = (255, 255, 255) if playing else CELL
        d.rounded_rectangle(box, 4, fill=fill, outline=ROW_COLORS[r] if a == app.selected else None, width=2)
        color = BG if playing and not app.mute_mode else (DIM if pad.mute or pad.sample is None else FG)
        _pad_text(d, pad.name, x + cw // 2, y + chh // 2, cw - 8, color)


def _list(d: ImageDraw.ImageDraw, items, cursor, empty, accent_first=0):
    if not items:
        d.text((W // 2, 100), empty, font=F_M, fill=DIM, anchor="mm")
        return
    top = max(0, min(cursor - 4, len(items) - 9))
    for row, name in enumerate(items[top:top + 9]):
        i = top + row
        y = 26 + row * 19
        if i == cursor:
            d.rectangle([4, y - 1, W - 4, y + 16], fill=(40, 40, 55))
        d.text((10, y), _fit(d, name, W - 30, F_M), font=F_M, fill=ACCENT if i < accent_first else FG)


def render(app: App) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _header(d, app)
    eng, pad = app.engine, app.pad
    sc = app.screen

    if sc in (Screen.PLAY, Screen.STEP):
        _pad_grid(d, app, 4, 24, 46, 44)
        x = 194
        d.text((x, 26), f"Пэд {app.pad_label(app.selected)}", font=F_S, fill=DIM)
        d.text((x, 38), _fit(d, pad.name, 122, F_L), font=F_L, fill=FG)
        _wave(d, pad.sample, x, 66, 120, 50, pad.start, pad.end, ROW_COLORS[(app.selected % BANK_SIZE) // 4])
        flags = [pad.mode.value]
        if pad.reverse:
            flags.append("назад")
        if pad.mute:
            flags.append("тихо")
        if pad.choke:
            flags.append(f"глуш {pad.choke}")
        d.text((x, 122), _fit(d, " · ".join(flags), 122), font=F_S, fill=DIM)
        if sc is Screen.STEP:
            d.text((x, 140), "Пэды = шаги", font=F_S, fill=ACCENT)
            d.text((x, 154), "SHIFT+пэд — выбор", font=F_S, fill=DIM)
        else:
            d.text((x, 140), f"Фейдер: {app.fader_mode}", font=F_S, fill=DIM)
            dl, dr = (eng.pads[p].name for p in app.decks)
            d.text((x, 184), _fit(d, f"◐ {dl}  ◑ {dr}", 122), font=F_S, fill=DIM)
            _bar(d, x, 155, 120, 8, eng.level, GREEN if eng.level < 0.9 else RED)
        if eng.seq.playing:
            for s in range(16):
                sx = x + s * 7.5
                d.rectangle([sx, 172, sx + 5, 178], fill=ACCENT if s == eng.seq.step else (50, 50, 60))

    elif sc is Screen.SAMPLE:
        rec = eng.recorder
        d.text((W // 2, 40), f"Запись на пэд {app.pad_label(app.selected)}", font=F_L, fill=FG, anchor="mm")
        status = {RecState.ARMED: "Жду звук… или тапни пэд", RecState.RECORDING: "● ИДЁТ ЗАПИСЬ",
                  RecState.IDLE: "", RecState.DONE: "Готово"}[rec.state]
        d.text((W // 2, 70), status, font=F_M, fill=RED if rec.state is RecState.RECORDING else ACCENT,
               anchor="mm")
        d.text((W // 2, 92), f"{rec.seconds:4.1f} с", font=F_L, fill=FG, anchor="mm")
        d.text((20, 116), "Вход", font=F_S, fill=DIM)
        _bar(d, 20, 132, 280, 14, rec.level, GREEN if rec.level < 0.9 else RED)
        tx = 21 + int(278 * rec.threshold)
        d.line([tx, 128, tx, 150], fill=ACCENT)
        d.text((20, 160), "SAMPLE — стоп / отмена", font=F_S, fill=DIM)

    elif sc is Screen.CHOP and app.chopper:
        ch = app.chopper
        n = ch.sample.frames
        d.text((6, 25), _fit(d, ch.sample.name, 200, F_M), font=F_M, fill=FG)
        d.text((W - 6, 26), f"{ch.mode.value} · {len(ch.slices)} срезов", font=F_S, fill=ACCENT, anchor="ra")
        x0, y0, w, h = 6, 46, W - 12, 92
        _wave(d, ch.sample, x0, y0, w, h, color=(90, 90, 100), marks=False)
        s, e = ch.slices[ch.cursor]
        _wave_part = (int(s / n * w), int(e / n * w))
        d.rectangle([x0 + _wave_part[0], y0, x0 + max(_wave_part[1] - 1, _wave_part[0]), y0 + h],
                    outline=ACCENT)
        for i, (a, _) in enumerate(ch.slices):
            mx = x0 + int(a / n * w)
            d.line([mx, y0 - 2, mx, y0 + h + 2], fill=BANK_COLORS[app.bank])
            if i < 16:
                d.text((mx + 2, y0 + h + 3), str(i + 1), font=F_S, fill=FG if i == ch.cursor else DIM)
        d.text((6, 160), f"◑ правая вертушка — срез · CHOP — на пэды банка {BANK_NAMES[app.bank]}", font=F_S, fill=DIM)
        d.text((6, 174), "Пэды — послушать · MODE — авто/ровно · STOP — выход", font=F_S, fill=DIM)

    elif sc is Screen.BROWSE:
        _list(d, app.browse_items, app.browse_cursor, "Пусто — запиши что-нибудь (SAMPLE)")
        d.text((W - 8, H - 50), f"→ пэд {app.pad_label(app.selected)}", font=F_S, fill=ACCENT, anchor="rb")

    elif sc is Screen.KITS:
        _list(d, app.kit_items(), app.kit_cursor, "", accent_first=2)
        d.text((W - 8, H - 50), f"сейчас: {app.kit_name}", font=F_S, fill=DIM, anchor="rb")

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
