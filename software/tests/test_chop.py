import unittest

import numpy as np

from sampley.chop import Chopper, ChopMode, equal, onsets
from sampley.engine import Engine
from sampley.kit_synth import clap, kick, snare, tom
from sampley.sample import Sample


def phrase():
    parts = [kick()[:9000], snare()[:7000], tom(160)[:8000], clap()[:6000], kick()[:5000], tom(110)[:9000]]
    starts = list(np.cumsum([0] + [len(p) for p in parts[:-1]]))
    return Sample.from_mono("Улица", np.concatenate(parts)).normalized(0.8), starts


class ChopTest(unittest.TestCase):
    def test_onsets_find_hits(self):
        s, truth = phrase()
        found = onsets(s, 0.5)
        self.assertEqual(len(found), len(truth))
        for f, t in zip(found, truth):
            self.assertLess(abs(f - t), 600)            # точнее 14 мс

    def test_silence_is_one_slice(self):
        s = Sample.from_mono("тишина", np.zeros(44100, dtype=np.float32))
        self.assertEqual(onsets(s), [0])

    def test_equal(self):
        s, _ = phrase()
        self.assertEqual(len(equal(s, 8)), 8)
        self.assertEqual(len(equal(s, 99)), 16)

    def test_chopper_apply_to_bank(self):
        s, truth = phrase()
        e = Engine()
        ch = Chopper(s)
        n = ch.apply(e, 16)
        self.assertEqual(n, len(truth))
        self.assertIs(e.pads[16].sample, e.pads[17].sample)          # один звук в памяти
        self.assertAlmostEqual(e.pads[17].start, e.pads[16].end)
        self.assertEqual(e.pads[18].name, "Улица·3")

    def test_modes_and_nudge(self):
        s, _ = phrase()
        ch = Chopper(s, mode=ChopMode.EQUAL, count=4)
        self.assertEqual(len(ch.slices), 4)
        ch.amount(+2)
        self.assertEqual(len(ch.slices), 6)
        a = ch.slices[0][1]
        ch.nudge(1, -2)
        self.assertLess(ch.slices[0][1], a)
        ch.select(-1)
        self.assertEqual(ch.cursor, 5)
        ch.toggle_mode()
        self.assertIs(ch.mode, ChopMode.AUTO)


if __name__ == "__main__":
    unittest.main()
