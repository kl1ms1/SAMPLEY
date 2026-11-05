import unittest

from sampley.sequencer import Sequencer


class SequencerTest(unittest.TestCase):
    def test_steps_and_timing(self):
        s = Sequencer(bpm=120)
        s.pattern.grid[3][0] = s.pattern.grid[3][4] = True
        s.start()
        ev = s.advance(int(s.frames_per_step() * 16))
        self.assertEqual([p for _, p in ev], [3, 3])
        self.assertEqual(ev[1][0], int(s.frames_per_step() * 4))

    def test_stopped_is_silent(self):
        s = Sequencer()
        s.pattern.grid[0][0] = True
        self.assertEqual(s.advance(10000), [])

    def test_swing_keeps_bar_length(self):
        s = Sequencer(bpm=100)
        s.swing = 0.3
        s.pattern.grid[0] = [True] * 16
        s.start()
        bar = s.frames_per_step() * 16
        ev = s.advance(int(bar) + 1)
        self.assertEqual(len(ev), 17)               # 16 шагов + первый шаг следующего такта
        self.assertGreater(ev[1][0], s.frames_per_step())

    def test_pattern_switch_on_bar(self):
        s = Sequencer()
        s.patterns[1].grid[5][0] = True
        s.start()
        s.advance(100)
        s.queued = 1
        self.assertEqual(s.current, 0)
        ev = s.advance(int(s.frames_per_step() * 16))
        self.assertEqual(s.current, 1)
        self.assertIn(5, [p for _, p in ev])

    def test_live_record_quantizes_without_double_hit(self):
        s = Sequencer()
        s.start()
        s.recording = True
        s.advance(int(s.frames_per_step() * 0.9))   # почти дошли до шага 1
        step = s.record_hit(7)
        self.assertEqual(step, 1)
        ev = s.advance(int(s.frames_per_step()))
        self.assertNotIn(7, [p for _, p in ev])     # уже сыграно вживую
        s.advance(int(s.frames_per_step() * 15))
        ev = s.advance(int(s.frames_per_step() * 2))
        self.assertIn(7, [p for _, p in ev])        # а со следующего круга — играет


if __name__ == "__main__":
    unittest.main()
