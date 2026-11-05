import unittest

import numpy as np

from sampley.recorder import Recorder, RecState


class RecorderTest(unittest.TestCase):
    def test_waits_for_sound_then_records(self):
        r = Recorder(threshold=0.1)
        r.arm()
        for _ in range(10):
            r.feed(np.zeros((256, 2)))
        self.assertIs(r.state, RecState.ARMED)
        r.feed(np.full((256, 2), 0.5))
        self.assertIs(r.state, RecState.RECORDING)
        r.feed(np.full((256, 2), 0.5))
        r.stop()
        s = r.take()
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.peak(), 0.9, places=3)
        self.assertGreaterEqual(s.frames, 512)

    def test_max_length(self):
        r = Recorder(max_seconds=0.01)
        r.start()
        for _ in range(10):
            r.feed(np.full((256, 1), 0.5))
        self.assertIs(r.state, RecState.DONE)
        self.assertEqual(r.take().frames, 441)

    def test_cancel(self):
        r = Recorder()
        r.start()
        r.feed(np.full((256, 2), 0.5))
        r.cancel()
        self.assertIsNone(r.take())


if __name__ == "__main__":
    unittest.main()
