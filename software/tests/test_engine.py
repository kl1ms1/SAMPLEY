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
