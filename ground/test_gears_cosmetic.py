"""Gigi maju bersifat kosmetik; N dan R tetap fungsional.

Dikunci di sini karena keduanya mudah tertukar: mengubah gear_ratios agar
gigi maju tidak lagi membatasi kecepatan TIDAK boleh ikut mematikan N
(harus selalu diam) maupun R (harus tetap mundur). Keduanya ditangani di
cabang terpisah _process_geared() dan tidak membaca gear_ratios sama sekali.
"""

from __future__ import annotations

import unittest

from rcground import config as cfg
from rcground.wheel import Wheel

THROTTLE = {
    "deadzone": 0.05,
    "expo": 0.0,
    "max_forward": 1.00,
    "max_reverse": 1.00,
}


def _wheel(ratios):
    wheel = Wheel.__new__(Wheel)
    wheel.tuning = {"throttle": THROTTLE, "brake": {"deadzone": 0.05, "strength": 1.0}}
    wheel._gear_ratios = list(ratios)
    return wheel


def _throttle(wheel, gear, gas=1.0):
    target, _ = wheel._process_geared(gas, 0.0, gear, THROTTLE)
    return target


class CosmeticGearTests(unittest.TestCase):
    def test_all_forward_gears_reach_full_speed(self):
        """Inti permintaan: gigi 1..6 tidak ada bedanya, semuanya 100%."""
        wheel = _wheel([1.0] * 6)
        speeds = [_throttle(wheel, gear) for gear in range(1, 7)]
        for gear, speed in zip(range(1, 7), speeds):
            with self.subTest(gigi=gear):
                self.assertAlmostEqual(speed, 1.0)
        self.assertEqual(len(set(round(s, 6) for s in speeds)), 1)

    def test_neutral_never_moves_whatever_the_pedal(self):
        wheel = _wheel([1.0] * 6)
        for gas in (0.0, 0.5, 1.0):
            with self.subTest(gas=gas):
                self.assertEqual(_throttle(wheel, 0, gas=gas), 0.0)

    def test_reverse_still_reverses_and_ignores_gear_ratios(self):
        """R memakai max_reverse, bukan gear_ratios -- buktikan tidak terpengaruh."""
        for ratios in ([1.0] * 6, [0.35, 0.55, 0.75, 0.90, 1.0, 1.0]):
            with self.subTest(ratios=ratios):
                self.assertAlmostEqual(_throttle(_wheel(ratios), -1), -1.0)

    def test_shipped_config_has_no_forward_gear_limiting(self):
        """config.example.yaml dan DEFAULT_CONFIG harus sepakat: tidak membatasi."""
        ratios = cfg.DEFAULT_CONFIG["shifter"]["gear_ratios"]
        self.assertTrue(all(r == 1.0 for r in ratios), ratios)
        self.assertEqual(len(ratios), 6, "jumlah gigi maju harus tetap 6")


if __name__ == "__main__":
    unittest.main()
