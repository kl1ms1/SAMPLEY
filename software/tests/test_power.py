import unittest

from sampley.power import Action, BatteryState, bq_ichg, bq_vreg, check, ntc_celsius


def st(p=50, v=3.8, t=25.0, ch=False):
    return BatteryState(p, v, t, ch)


class PowerTest(unittest.TestCase):
    def test_normal(self):
        self.assertIs(check(st()), Action.OK)

    def test_empty_shutdown_by_percent_or_volts(self):
        self.assertIs(check(st(p=3)), Action.SHUTDOWN_EMPTY)
        self.assertIs(check(st(p=40, v=3.35)), Action.SHUTDOWN_EMPTY)    # процентам не верим, если напряжение низкое
        self.assertIs(check(st(p=3, ch=True)), Action.OK)                # на зарядке — не выключаемся

    def test_low_warning(self):
        self.assertIs(check(st(p=12)), Action.LOW)

    def test_heat(self):
        self.assertIs(check(st(t=52)), Action.HOT)
        self.assertIs(check(st(t=61, ch=True)), Action.SHUTDOWN_HOT)     # перегрев важнее всего
        self.assertIs(check(st(t=-3, ch=True)), Action.COLD)

    def test_unknown_values(self):
        self.assertIs(check(BatteryState(None, None, None, False)), Action.OK)

    def test_bq_registers(self):
        self.assertEqual(bq_vreg(4.208), 0x5E)                            # заводское значение BQ25895
        self.assertEqual(bq_vreg(4.096), 0x42)                            # бережная зарядка
        self.assertEqual(bq_ichg(1024), 16)

    def test_ntc(self):
        # при 25 °C NTC = 10 кОм → вычисляем TS% этого делителя и обратно
        r_par = 10000 * 30100 / (10000 + 30100)
        ts = 100 * r_par / (5230 + r_par)
        self.assertAlmostEqual(ntc_celsius(ts), 25.0, delta=0.2)
        self.assertIsNone(ntc_celsius(99.0))


if __name__ == "__main__":
    unittest.main()
