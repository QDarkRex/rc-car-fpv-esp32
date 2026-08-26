"""Stir tanpa calibration.yaml tidak boleh mengarang input.

Regresi nyata yang ditangkap di sini: default lama menebak axis gas = 1 DAN
menebak pedal-lepas ada di -1.0. Pada stir yang axis 1-nya diam di 0.0, itu
terbaca sebagai gas 50% tanpa pedal disentuh -- yang muncul ke pengguna
sebagai "Tidak bisa arm: lepaskan pedal dulu" padahal kakinya tidak di pedal.
"""

from __future__ import annotations

import unittest

from rcground.wheel import Wheel


class _FakeJoystick:
    """Stir yang semua axis-nya diam di 0.0 -- kasus yang memicu bug lama."""

    def __init__(self, axes=5, buttons=12, rest=0.0):
        self._axes = [rest] * axes
        self._buttons = [False] * buttons

    def get_init(self):
        return True

    def get_name(self):
        return "Fake Wheel"

    def get_numaxes(self):
        return len(self._axes)

    def get_numbuttons(self):
        return len(self._buttons)

    def get_axis(self, i):
        return self._axes[i]

    def get_button(self, i):
        return self._buttons[i]


def _wheel(calibration, rest=0.0):
    wheel = Wheel.__new__(Wheel)
    wheel.calibration = calibration
    wheel.tuning = {
        "steering": {"deadzone": 0.03, "expo": 0.0},
        "throttle": {"deadzone": 0.05, "expo": 0.0, "max_forward": 1.0,
                     "max_reverse": 1.0, "slew_rate": 0.0},
        "brake": {"deadzone": 0.05, "strength": 1.0},
    }
    wheel.joystick = _FakeJoystick(rest=rest)
    wheel.name = "Fake Wheel"
    wheel._prev_arm = False
    wheel._prev_horn = False
    wheel._throttle_out = 0.0
    wheel._trim = 0.0
    wheel._shifter_cal = calibration.get("shifter") or {}
    wheel.shifter_enabled = False
    wheel._gear_ratios = []
    wheel._seq_gear = 0
    wheel._prev_up = False
    wheel._prev_down = False
    return wheel


class UncalibratedWheelTests(unittest.TestCase):
    def test_empty_calibration_reports_no_pedal_input(self):
        """Inti bug: tanpa kalibrasi, gas/rem/throttle harus benar-benar 0."""
        for rest in (-1.0, -0.5, 0.0, 0.5, 1.0):
            with self.subTest(axis_rest=rest):
                state = _wheel({}, rest=rest).read(0.02)
                self.assertEqual(state.gas, 0.0)
                self.assertEqual(state.brake, 0.0)
                self.assertEqual(state.throttle, 0.0)
                self.assertEqual(state.steer, 0.0)

    def test_uncalibrated_wheel_can_arm(self):
        """Konsekuensi yang benar-benar dirasakan pengguna: arm tidak diblokir.

        ARM_THROTTLE_LIMIT di main.py adalah 0.02; throttle 0.0 lolos.
        """
        state = _wheel({}, rest=0.0).read(0.02)
        self.assertLessEqual(abs(state.throttle), 0.02)

    def test_calibrated_wheel_still_reads_pedal_normally(self):
        """Kalibrasi yang ada harus tetap bekerja persis seperti sebelumnya."""
        calibration = {
            "axes": {
                "steer": {"axis": 0, "min": -1.0, "center": 0.0, "max": 1.0},
                "gas": {"axis": 1, "released": 0.0, "pressed": 1.0},
                "brake": {"axis": 2, "released": 0.0, "pressed": 1.0},
            },
            "buttons": {"arm": 0, "estop": 1, "horn": 2},
        }
        wheel = _wheel(calibration, rest=0.0)
        state = wheel.read(0.02)
        self.assertEqual(state.gas, 0.0)      # diam di titik "released"

        wheel.joystick._axes[1] = 1.0          # gas diinjak penuh
        state = wheel.read(0.02)
        self.assertAlmostEqual(state.gas, 1.0)
        self.assertGreater(state.throttle, 0.5)

    def test_partial_calibration_only_zeroes_the_missing_axis(self):
        """Kalibrasi setengah jadi: yang ada tetap dipakai, yang hilang jadi 0."""
        calibration = {
            "axes": {"gas": {"axis": 1, "released": 0.0, "pressed": 1.0}},
        }
        wheel = _wheel(calibration, rest=0.0)
        wheel.joystick._axes[1] = 1.0
        state = wheel.read(0.02)
        self.assertAlmostEqual(state.gas, 1.0)   # ada -> terbaca
        self.assertEqual(state.brake, 0.0)       # hilang -> 0, bukan tebakan
        self.assertEqual(state.steer, 0.0)       # hilang -> 0, bukan tebakan


if __name__ == "__main__":
    unittest.main()
