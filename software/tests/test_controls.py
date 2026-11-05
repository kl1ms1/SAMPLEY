import unittest

from sampley.controls import BUTTON_LEDS, Button, Kind, ProtocolError, leds_line, parse


class ProtocolTest(unittest.TestCase):
    def test_parse(self):
        e = parse("P 5 1\n")
        self.assertEqual((e.kind, e.index, e.value), (Kind.PAD, 5, 1))
        self.assertAlmostEqual(parse("P 0 1 64").velocity, 64 / 127)
        self.assertEqual(parse("B CHOP 1").button, Button.CHOP)
        e = parse("E 3 -2")
        self.assertEqual((e.kind, e.index, e.value), (Kind.ENCODER, 3, -2))
        self.assertEqual(parse("K 1 1").kind, Kind.ENC_PUSH)
        e = parse("A 0 512")
        self.assertEqual((e.kind, e.index, e.value), (Kind.ANALOG, 0, 512))
        self.assertEqual(parse("S OFF").value, 0)
        self.assertEqual(parse("V sampley-mcu 2").text, "sampley-mcu 2")

    def test_bad_lines(self):
        for line in ["", "P 16 1", "E 9 1", "B FOO 1", "X", "P a b", "S MAYBE", "A 2 5", "A 0 2000"]:
            with self.assertRaises(ProtocolError, msg=line):
                parse(line)

    def test_led_line(self):
        self.assertEqual(leds_line([(1, 2, 3)] * 2), "LA 010203 010203\n")

    def test_every_button_has_led(self):
        self.assertEqual(set(BUTTON_LEDS), set(Button))

    def test_firmware_keymap_matches(self):
        """Имена кнопок в прошивке Pico совпадают с протоколом."""
        import os
        import re
        fw = open(os.path.join(os.path.dirname(__file__), "..", "..", "firmware", "pico", "main.py"),
                  encoding="utf-8").read()
        names = set(re.findall(r'\("B", "(\w+)"\)', fw))
        self.assertEqual(names, {b.value for b in Button})
        order = re.search(r"BUTTON_LEDS = \[(.*?)\]", fw, re.S).group(1)
        self.assertEqual(re.findall(r'"(\w+)"', order), [b.value for b in BUTTON_LEDS])


if __name__ == "__main__":
    unittest.main()
