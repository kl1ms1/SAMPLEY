import unittest

from sampley.controls import Button, Kind, ProtocolError, led_line, leds_line, parse


class ProtocolTest(unittest.TestCase):
    def test_parse(self):
        e = parse("P 5 1\n")
        self.assertEqual((e.kind, e.index, e.value), (Kind.PAD, 5, 1))
        self.assertAlmostEqual(parse("P 0 1 64").velocity, 64 / 127)
        self.assertEqual(parse("B SHIFT 1").button, Button.SHIFT)
        e = parse("E 3 -2")
        self.assertEqual((e.kind, e.index, e.value), (Kind.ENCODER, 3, -2))
        self.assertEqual(parse("K 1 1").kind, Kind.ENC_PUSH)
        self.assertEqual(parse("S OFF").value, 0)
        self.assertEqual(parse("V sampley-mcu 1").text, "sampley-mcu 1")

    def test_bad_lines(self):
        for line in ["", "P 16 1", "E 9 1", "B FOO 1", "X", "P a b", "S MAYBE"]:
            with self.assertRaises(ProtocolError, msg=line):
                parse(line)

    def test_led_lines(self):
        self.assertEqual(led_line(3, (255, 0, 16)), "L 3 FF0010\n")
        self.assertEqual(leds_line([(1, 2, 3)] * 2), "LA 010203 010203\n")


if __name__ == "__main__":
    unittest.main()
