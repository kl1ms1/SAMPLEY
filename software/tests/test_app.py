import os
import tempfile
import unittest

from sampley.app import App, Screen
from sampley.controls import Button, Event, Kind
from sampley.engine import Engine, Mode
from sampley.kit import list_kits, load_default
from sampley.recorder import RecState


def btn(b, v=1):
    return Event(Kind.BUTTON, value=v, button=b)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = Engine()
        load_default(self.e)
        self.t = [0.0]
        self.off = []
        self.app = App(self.e, kits_root=self.tmp.name, clock=lambda: self.t[0],
                       on_shutdown=lambda: self.off.append(1))

    def tearDown(self):
        self.tmp.cleanup()

    def test_pad_plays_and_selects(self):
        self.app.handle(Event(Kind.PAD, 5, 1))
        self.e.render(256)
        self.assertEqual(self.app.selected, 5)
        self.assertIn(5, self.e.playing_pads)

    def test_shift_pad_selects_silently(self):
        self.app.handle(btn(Button.SHIFT))
        self.app.handle(Event(Kind.PAD, 9, 1))
        self.e.render(256)
        self.assertEqual(self.app.selected, 9)
        self.assertEqual(self.e.playing_pads, set())

    def test_encoders_edit_selected_pad(self):
        self.app.handle(Event(Kind.PAD, 2, 1))
        self.app.handle(Event(Kind.ENCODER, 1, 3))
        self.app.handle(Event(Kind.ENCODER, 0, -50))
        self.assertEqual(self.e.pads[2].pitch, 3)
        self.assertEqual(self.e.pads[2].volume, 0.0)
        self.app.handle(Event(Kind.ENC_PUSH, 3, 1))
        self.assertIs(self.e.pads[2].mode, Mode.GATE)

    def test_shift_encoders_global(self):
        self.app.handle(btn(Button.SHIFT))
        self.app.handle(Event(Kind.ENCODER, 1, 10))
        self.app.handle(Event(Kind.ENCODER, 3, 1))
        self.assertEqual(self.e.seq.bpm, 130)
        self.assertEqual(self.e.seq.current, 1)

    def test_step_mode_toggles_steps(self):
        self.app.handle(btn(Button.SHIFT))
        self.app.handle(Event(Kind.PAD, 4, 1))           # дорожка пэда 5
        self.app.handle(btn(Button.PLAY))
        self.app.handle(btn(Button.SHIFT, 0))
        self.assertIs(self.app.screen, Screen.STEP)
        self.app.handle(Event(Kind.PAD, 10, 1))
        self.assertTrue(self.e.seq.pattern.grid[4][10])

    def test_record_flow(self):
        import numpy as np
        self.app.handle(Event(Kind.PAD, 15, 1))
        self.app.handle(btn(Button.REC))
        self.assertIs(self.app.screen, Screen.SAMPLE)
        self.assertIs(self.e.recorder.state, RecState.ARMED)
        for _ in range(20):
            self.e.render(256, np.full((256, 2), 0.4, dtype=np.float32))
        self.app.handle(btn(Button.REC))
        self.e.render(256)
        self.app.tick()
        self.assertIs(self.app.screen, Screen.PLAY)
        self.assertTrue(self.e.pads[15].sample.name.startswith("Запись"))

    def test_rec_while_playing_is_overdub(self):
        self.app.handle(btn(Button.PLAY))
        self.app.handle(btn(Button.REC))
        self.assertTrue(self.e.seq.recording)
        self.assertIs(self.app.screen, Screen.PLAY)

    def test_kits_save_and_load(self):
        self.e.pads[0].pitch = 5
        self.app.handle(btn(Button.SHIFT)); self.app.handle(btn(Button.REC)); self.app.handle(btn(Button.SHIFT, 0))
        self.assertIs(self.app.screen, Screen.KITS)
        self.app.handle(Event(Kind.ENC_PUSH, 0, 1))      # «Сохранить как новый»
        self.assertEqual(list_kits(self.tmp.name), ["kit-01"])
        self.e.pads[0].pitch = 0
        self.e.seq.patterns[0].clear()
        self.app.screen = Screen.KITS
        self.app.kit_cursor = 2
        self.app.handle(Event(Kind.ENC_PUSH, 0, 1))
        self.assertEqual(self.e.pads[0].pitch, 5)
        self.assertTrue(self.e.seq.patterns[0].grid[0][0])
        self.assertEqual(self.e.pads[3].choke, 1)

    def test_power_switch_saves_and_shuts_down(self):
        self.app.handle(Event(Kind.POWER, value=0))
        self.assertEqual(self.off, [1])
        self.assertIn("autosave", list_kits(self.tmp.name))

    def test_tap_tempo(self):
        self.app.handle(btn(Button.SHIFT))
        for t in (0.0, 0.5, 1.0, 1.5):
            self.t[0] = t
            self.app.handle(Event(Kind.ENC_PUSH, 1, 1))
        self.assertEqual(self.e.seq.bpm, 120)

    def test_render_all_screens(self):
        from sampley import ui
        for s in Screen:
            self.app.screen = s
            img = ui.render(self.app)
            self.assertEqual(img.size, (320, 240))
            self.assertEqual(len(ui.to_rgb565(img)), 320 * 240 * 2)


if __name__ == "__main__":
    unittest.main()
