import unittest

from sampley.board import profile_for_model
from sampley.pins import PINS, free_pins


class BoardTest(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(profile_for_model("Raspberry Pi Zero 2 W Rev 1.0\x00").key, "zero_2w")
        self.assertEqual(profile_for_model("Raspberry Pi Zero W Rev 1.1\x00").key, "zero_w")
        self.assertEqual(profile_for_model(None).key, "pc")

    def test_pins_unique(self):
        phys = [p.phys for p in PINS.values()]
        self.assertEqual(len(phys), len(set(phys)))
        self.assertTrue(all(p.bcm not in (2, 3, 14, 15, 18, 19, 20, 21) for p in free_pins()))


if __name__ == "__main__":
    unittest.main()
