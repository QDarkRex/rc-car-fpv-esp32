"""Static guardrails for the reserved firmware calibration path."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FirmwareCalibrationGuards(unittest.TestCase):
    def test_firmware_requires_zero_motor_fields_and_has_steering_only_branch(self):
        link = (ROOT / "firmware" / "rc_car_esp32" / "link.cpp").read_text(encoding="utf-8")
        main = (ROOT / "firmware" / "rc_car_esp32" / "rc_car_esp32.ino").read_text(encoding="utf-8")
        drive = (ROOT / "firmware" / "rc_car_esp32" / "drive.cpp").read_text(encoding="utf-8")
        self.assertIn("RC_FLAG_SERVO_CALIBRATION", link)
        self.assertIn("packet.throttle == 0", link)
        self.assertIn("packet.brake == 0", link)
        self.assertIn("servoCalibration()", main)
        self.assertIn("setServoCalibration", main)
        self.assertIn("_appliedThrottle = 0", drive)
        timeout_guard = link.index("if (_servoCalibration &&")
        failsafe_switch = link.index("#if !FAILSAFE_ENABLED")
        self.assertLess(timeout_guard, failsafe_switch)


if __name__ == "__main__":
    unittest.main()
