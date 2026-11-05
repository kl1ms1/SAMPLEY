import unittest

import numpy as np

from sampley.engine import FADE, Engine, Mode
from sampley.sample import Sample


def tone(n=4410, v=0.5):
    return Sample.from_mono("t", np.full(n, v, dtype=np.float32))


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.e = Engine(max_voices=4, master=1.0)
        self.e.pads[0].sample = tone()

    def test_silence_without_hits(self):
        self.assertEqual(np.abs(self.e.render(256)).max(), 0)

    def test_oneshot_plays_and_ends(self):
        self.e.note_on(0)
        self.assertGreater(np.abs(self.e.render(256)).max(), 0.1)
        for _ in range(30):
            self.e.render(256)
        self.assertEqual(self.e.voices, [])

    def test_gate_stops_on_release(self):
        self.e.pads[0].mode = Mode.GATE
        self.e.note_on(0)
        self.e.render(256)
        self.e.note_off(0)
        self.e.render(FADE + 10)
        self.assertEqual(np.abs(self.e.render(256)).max(), 0)

    def test_loop_keeps_playing(self):
        self.e.pads[0].mode = Mode.LOOP
        self.e.note_on(0)
        for _ in range(100):
            out = self.e.render(256)
        self.assertGreater(np.abs(out).max(), 0.1)

    def test_toggle_second_hit_stops(self):
        self.e.pads[0].mode = Mode.TOGGLE
        self.e.note_on(0); self.e.render(256)
        self.e.note_on(0); self.e.render(FADE + 10)
        self.assertEqual(np.abs(self.e.render(256)).max(), 0)

    def test_pitch_up_shortens(self):
        self.e.pads[0].pitch = 12
        self.e.note_on(0)
        n = 0
        while True:
            out = self.e.render(64)
            if not self.e.voices:
                break
            n += 64
        self.assertAlmostEqual(n, 4410 / 2, delta=128)

    def test_choke_group(self):
        self.e.pads[1].sample = tone()
        self.e.pads[0].choke = self.e.pads[1].choke = 1
        self.e.note_on(0); self.e.render(64)
        self.e.note_on(1); self.e.render(FADE + 10)
        self.assertEqual({v.pad for v in self.e.voices}, {1})

    def test_voice_limit(self):
        for i in range(8):
            self.e.pads[i].sample = tone()
            self.e.note_on(i)
        self.e.render(64)
        self.assertLessEqual(len(self.e.voices), 4)

    def test_pan(self):
        self.e.pads[0].pan = -1
        self.e.note_on(0)
        out = self.e.render(256)
        self.assertGreater(np.abs(out[:, 0]).max(), 0.1)
        self.assertLess(np.abs(out[:, 1]).max(), 1e-3)

    def test_sequencer_hits_sample_accurate(self):
        self.e.pads[0].sample = Sample.from_mono("click", np.ones(10, dtype=np.float32))
        self.e.seq.pattern.grid[0][1] = True
        self.e.seq.start()
        fps = self.e.seq.frames_per_step()
        out = np.concatenate([self.e.render(256) for _ in range(40)])
        first = int(np.flatnonzero(np.abs(out[:, 0]) > 0.01)[0])
        self.assertAlmostEqual(first, fps, delta=1)


if __name__ == "__main__":
    unittest.main()


class PerformanceFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.e = Engine(max_voices=16, master=1.0)
        self.e.pads[0].sample = Sample.from_mono("click", np.ones(50, dtype=np.float32))

    def hits(self, out):
        x = np.abs(out[:, 0]) > 0.01
        return int(np.count_nonzero(x[1:] & ~x[:-1]) + x[0])

    def test_note_repeat_follows_tempo(self):
        self.e.seq.bpm = 120
        self.e.repeat_rate = "1/16"
        self.e.repeat_on(0)
        out = np.concatenate([self.e.render(256) for _ in range(int(44100 / 256))])   # ≈1 с
        self.assertEqual(self.hits(out), 8)                 # 120 BPM: 8 шестнадцатых в секунду
        self.e.repeat_off(0)
        out = np.concatenate([self.e.render(256) for _ in range(50)])
        self.assertEqual(self.hits(out), 0)

    def test_levels_keys_are_polyphonic(self):
        self.e.pads[0].sample = tone(44100)
        self.e.note_on(0, semis=0, key=("lv", 0))
        self.e.note_on(0, semis=7, key=("lv", 7))
        self.e.render(256)
        self.assertEqual(len([v for v in self.e.voices if v.releasing < 0]), 2)
        self.assertAlmostEqual(self.e.voices[1].rate, 2 ** (7 / 12))

    def test_fader_tune_speeds_up(self):
        self.e.pads[0].sample = tone(4410)
        self.e.tune = 12
        self.e.note_on(0)
        n = 0
        while True:
            self.e.render(64)
            if not self.e.voices:
                break
            n += 64
        self.assertAlmostEqual(n, 4410 / 2, delta=128)

    def test_filter_cuts_highs(self):
        rng = np.random.default_rng(0)
        self.e.pads[0].sample = Sample.from_mono("шум", rng.uniform(-0.5, 0.5, 44100).astype(np.float32))
        self.e.note_on(0)
        dry = self.e.render(4096)
        self.e.stop_all(); self.e.render(512)
        self.e.filter = -0.9
        self.e.note_on(0)
        self.e.render(1024)
        wet = self.e.render(4096)
        hf = lambda x: np.abs(np.diff(x[:, 0])).mean()
        self.assertLess(hf(wet), hf(dry) * 0.2)
