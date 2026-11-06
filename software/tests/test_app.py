import tempfile
import unittest

import numpy as np

from sampley.app import App, Screen
from sampley.controls import FADER, VOLUME, Button, Event, Kind
from sampley.engine import Mode
from sampley.engine import Engine
from sampley.kit import list_kits, load_default
from sampley.library import list_samples
from sampley.recorder import RecState


def btn(b, v=1):
    return Event(Kind.BUTTON, value=v, button=b)


def pad(i, v=1):
    return Event(Kind.PAD, i, v)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = Engine()
        load_default(self.e)
        self.t = [0.0]
        self.off = []
        self.app = App(self.e, kits_root=self.tmp.name + "/kits", samples_root=self.tmp.name + "/samples",
                       clock=lambda: self.t[0], on_shutdown=lambda: self.off.append(1))

    def tearDown(self):
        self.tmp.cleanup()

    def press(self, b):
        self.app.handle(btn(b))
        self.app.handle(btn(b, 0))

    def test_pad_plays_and_selects(self):
        self.app.handle(pad(5))
        self.e.render(256)
        self.assertEqual(self.app.selected, 5)
        self.assertIn(5, self.e.playing_pads)

    def test_shift_pad_selects_silently(self):
        self.app.handle(btn(Button.SHIFT))
        self.app.handle(pad(9))
        self.e.render(256)
        self.assertEqual(self.app.selected, 9)
        self.assertEqual(self.e.playing_pads, set())

    def test_knobs_edit_selected_pad(self):
        self.app.handle(pad(2))
        self.app.handle(Event(Kind.ENCODER, 1, 3))
        self.app.handle(Event(Kind.ENCODER, 0, -50))
        self.app.handle(Event(Kind.ENCODER, 2, -4))
        p = self.e.pads[2]
        self.assertEqual((p.pitch, p.volume, p.pan), (3, 0.0, -0.2))
        self.press(Button.MODE)
        self.assertIs(p.mode, Mode.GATE)

    def test_wheel_and_shift_knobs(self):
        self.app.handle(Event(Kind.ENCODER, 3, 5))
        self.assertEqual(self.e.seq.bpm, 125)
        self.app.handle(btn(Button.SHIFT))
        self.app.handle(Event(Kind.ENCODER, 1, 1))
        self.app.handle(Event(Kind.ENCODER, 0, 5))
        self.assertEqual(self.e.seq.current, 1)
        self.assertEqual(self.e.seq.swing, 0.1)

    def test_banks(self):
        self.press(Button.BANK)
        self.app.handle(pad(0))
        self.assertEqual(self.app.selected, 16)
        self.app.handle(btn(Button.SHIFT)); self.press(Button.BANK); self.app.handle(btn(Button.SHIFT, 0))
        self.assertEqual(self.app.bank, 0)

    def test_step_mode_toggles_steps(self):
        self.app.handle(btn(Button.SHIFT)); self.app.handle(pad(4)); self.app.handle(btn(Button.SHIFT, 0))
        self.press(Button.STEP)
        self.assertIs(self.app.screen, Screen.STEP)
        self.app.handle(pad(10))
        self.assertTrue(self.e.seq.pattern.grid[4][10])

    def test_tap_pad_to_record_then_chop(self):
        self.press(Button.SAMPLE)
        self.assertIs(self.app.screen, Screen.SAMPLE)
        self.assertIs(self.e.recorder.state, RecState.ARMED)
        self.app.handle(pad(15))                                   # «тапни пэд — пишем»
        self.assertIs(self.e.recorder.state, RecState.RECORDING)
        sig = np.zeros((256, 2), dtype=np.float32)
        for k in range(60):                                        # 4 «удара»
            blk = sig.copy()
            if k % 15 == 0:
                blk[:] = 0.6
            self.e.render(256, blk)
        self.press(Button.SAMPLE)
        self.e.render(256)
        self.app.tick()
        self.assertIs(self.app.screen, Screen.PLAY)
        self.assertEqual(self.app.selected, 15)
        self.assertTrue(self.e.pads[15].sample.name.startswith("Запись"))
        self.assertEqual(len(list_samples(self.app.samples_root)), 1)   # копия на карте
        self.press(Button.CHOP)
        self.assertIs(self.app.screen, Screen.CHOP)
        self.app.handle(Event(Kind.ENC_PUSH, 3, 1))                # разложить по банку
        self.assertIs(self.app.screen, Screen.PLAY)
        self.assertIs(self.e.pads[0].sample, self.e.pads[1].sample)

    def test_chop_empty_pad_says_so(self):
        self.e.pads[0].sample = None
        self.press(Button.CHOP)
        self.assertIs(self.app.screen, Screen.PLAY)
        self.assertIn("пустой", self.app.toast)

    def test_rec_then_play_records_pattern(self):
        self.press(Button.REC)
        self.assertTrue(self.e.seq.recording)
        self.press(Button.PLAY)
        self.assertTrue(self.e.seq.playing)
        self.e.seq.pattern.clear()
        self.e.render(256)
        self.app.handle(pad(6))
        self.e.render(256)
        self.assertTrue(any(self.e.seq.pattern.grid[6]))
        self.press(Button.STOP)
        self.assertFalse(self.e.seq.playing)

    def test_mute_mode(self):
        self.press(Button.MUTE)
        self.app.handle(pad(3))
        self.assertTrue(self.e.pads[3].mute)
        self.e.render(256)
        self.assertEqual(self.e.playing_pads, set())

    def test_levels_mode(self):
        self.app.handle(pad(8)); self.app.handle(pad(8, 0))
        self.press(Button.LEVELS)
        self.app.handle(pad(0))                                    # верхний левый = +12
        self.e.render(64)
        self.assertEqual(self.app.selected, 8)
        v = [v for v in self.e.voices if v.key == ("lv", 0)][0]
        self.assertAlmostEqual(v.rate, 2.0)

    def test_note_repeat(self):
        self.app.handle(btn(Button.REPEAT))
        self.app.handle(pad(0))
        self.assertTrue(self.e._repeat or not self.e._cmds.empty())
        self.e.render(256)
        self.assertIn(0, self.e._repeat)
        self.app.handle(btn(Button.REPEAT, 0))
        self.e.render(256)
        self.assertEqual(self.e._repeat, {})

    def test_fader_and_volume(self):
        self.app.handle(Event(Kind.ANALOG, FADER, 1023))
        self.assertEqual(self.e.tune, 12)
        self.app.handle(Event(Kind.ANALOG, FADER, 512))
        self.assertEqual(self.e.tune, 0)
        self.app.handle(btn(Button.SHIFT)); self.press(Button.TAP); self.app.handle(btn(Button.SHIFT, 0))
        self.app.handle(Event(Kind.ANALOG, FADER, 0))
        self.assertEqual(self.e.filter, -1.0)
        self.app.handle(Event(Kind.ANALOG, VOLUME, 0))
        self.assertEqual(self.e.master, 0.0)

    def test_browse_loads_recording(self):
        from sampley.library import save_recording
        from sampley.sample import Sample
        save_recording(Sample.from_mono("x", np.full(1000, 0.3, dtype=np.float32)), self.app.samples_root)
        self.app.handle(btn(Button.SHIFT)); self.app.handle(pad(7)); self.app.handle(btn(Button.SHIFT, 0))
        self.press(Button.BROWSE)
        self.assertEqual(len(self.app.browse_items), 1)
        self.app.handle(Event(Kind.ENC_PUSH, 3, 1))
        self.assertTrue(self.e.pads[7].sample.name.startswith("rec-"))

    def test_kits_save_and_load(self):
        self.e.pads[0].pitch = 5
        self.press(Button.KITS)
        self.assertIs(self.app.screen, Screen.KITS)
        self.app.handle(Event(Kind.ENC_PUSH, 3, 1))                # «Сохранить как новый»
        self.assertEqual(list_kits(self.app.kits_root), ["kit-01"])
        self.e.pads[0].pitch = 0
        self.e.seq.patterns[0].clear()
        self.press(Button.KITS)
        self.app.handle(Event(Kind.ENCODER, 3, 2))
        self.app.handle(Event(Kind.ENC_PUSH, 3, 1))
        self.assertEqual(self.e.pads[0].pitch, 5)
        self.assertTrue(self.e.seq.patterns[0].grid[0][0])
        self.assertEqual(self.e.pads[3].choke, 1)

    def test_chopped_kit_stores_sound_once(self):
        import os
        from sampley.chop import Chopper
        from sampley.kit import load_kit, save_kit
        long = np.concatenate([self.e.pads[i].sample.data for i in range(4)])
        from sampley.sample import Sample
        Chopper(Sample("длинный", long)).apply(self.e, 16)
        path = save_kit(self.e, "k", self.app.kits_root)
        self.assertEqual(len([f for f in os.listdir(path) if f.endswith(".wav")]), 17)   # 16 + длинный
        load_kit(self.e, "k", self.app.kits_root)
        self.assertIs(self.e.pads[16].sample, self.e.pads[17].sample)
        self.assertEqual(self.e.pads[17].name, "длинный·2")

    def test_power_switch_saves_and_shuts_down(self):
        self.app.handle(Event(Kind.POWER, value=0))
        self.assertEqual(self.off, [1])
        self.assertIn("autosave", list_kits(self.app.kits_root))

    def test_jogs(self):
        self.app.handle(Event(Kind.JOG_TOUCH, 1, 1))               # палец на правой + пэд — положить пэд
        self.app.handle(pad(5))
        self.assertEqual(self.app.decks[1], 5)
        self.e.render(256)
        self.assertEqual(self.e.jogs[1]["pad"], 5)
        self.app.handle(Event(Kind.JOG, 1, 300))                   # крутим под пальцем — скретч
        self.e.render(256)
        self.assertTrue(self.e.scratching)
        self.app.handle(Event(Kind.JOG_TOUCH, 1, 0))
        self.app.handle(btn(Button.SHIFT))
        self.app.handle(Event(Kind.JOG, 0, 1000))                  # SHIFT + вертушка — фильтр
        self.assertGreater(self.e.filter, 0.5)

    def test_stutter_button_and_roll(self):
        self.app.handle(btn(Button.STUTTER))
        self.assertTrue(self.app.stutter_active)
        self.e.render(256)
        self.assertTrue(self.e.stuttering)
        self.app.handle(Event(Kind.JOG, 1, 450))                   # правая вертушка — повтор короче
        self.assertEqual(self.e.stutter_div, "1/16")
        self.app.handle(btn(Button.STUTTER, 0))
        self.e.render(256)
        self.assertFalse(self.e.stuttering)
        self.app.handle(btn(Button.SHIFT)); self.app.handle(btn(Button.STUTTER)); self.app.handle(btn(Button.SHIFT, 0))
        self.app.handle(btn(Button.STUTTER, 0))
        self.e.render(256)
        self.assertTrue(self.e.stuttering)                         # зафиксирован

    def test_tap_tempo(self):
        for t in (0.0, 0.5, 1.0, 1.5):
            self.t[0] = t
            self.press(Button.TAP)
        self.assertEqual(self.e.seq.bpm, 120)

    def test_leds(self):
        from sampley.controls import BUTTON_LEDS
        self.assertEqual(len(self.app.led_colors()), 16 + len(BUTTON_LEDS))

    def test_render_all_screens(self):
        from sampley import ui
        from sampley.chop import Chopper
        self.app.chopper = Chopper(self.e.pads[0].sample)
        for flags in ((False, False), (True, False), (False, True)):
            self.app.mute_mode, self.app.levels_mode = flags
            for s in Screen:
                self.app.screen = s
                img = ui.render(self.app)
                self.assertEqual(img.size, (320, 240))
        self.assertEqual(len(ui.to_rgb565(img)), 320 * 240 * 2)


if __name__ == "__main__":
    unittest.main()
