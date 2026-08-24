"""Pure servo mapping and calibration safety tests."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from calibrate import safe_center_packets
from calibrate import servo_preview_packet
from rcground import config as cfg
from rcground import protocol as proto
from rcground.link import Link
from rcground.wheel import map_servo_output, validate_servo_points


class _Link:
    def __init__(self):
        self.packets = []

    def send(self, *args):
        self.packets.append(args)


class ServoTests(unittest.TestCase):
    def test_default_mapping_is_historical_identity(self):
        for value in (-1.0, -0.25, 0.0, 0.25, 1.0):
            self.assertAlmostEqual(map_servo_output(value), value)

    def test_asymmetric_mapping_and_clamp(self):
        self.assertAlmostEqual(map_servo_output(-0.5, -0.8, 0.1, 0.9), -0.35)
        self.assertAlmostEqual(map_servo_output(0.5, -0.8, 0.1, 0.9), 0.5)
        self.assertEqual(map_servo_output(-2.0, -0.8, 0.1, 0.9), -0.8)
        self.assertEqual(map_servo_output(2.0, -0.8, 0.1, 0.9), 0.9)

    def test_validation_rejects_bad_order_and_range(self):
        with self.assertRaises(ValueError):
            validate_servo_points(0.0, -0.1, 1.0)
        with self.assertRaises(ValueError):
            validate_servo_points(-1.1, 0.0, 1.0)

    def test_safe_center_packets_are_disarmed_and_neutral(self):
        link = _Link()
        safe_center_packets(link, count=3)
        self.assertEqual(link.packets, [(0.0, 0.0, False, 0.0)] * 3)

    def test_preview_sets_reserved_flag_and_remains_disarmed(self):
        class PreviewLink:
            def __init__(self):
                self.calls = []

            def send(self, *args, **kwargs):
                self.calls.append((args, kwargs))

        link = PreviewLink()
        servo_preview_packet(link, 0.4)
        self.assertEqual(link.calls, [((0.4, 0.0, False, 0.0), {"servo_calibration": True})])

    def test_link_forces_calibration_motor_fields_and_flag(self):
        class Socket:
            def __init__(self):
                self.packets = []

            def sendto(self, packet, address):
                self.packets.append((packet, address))

        link = Link.__new__(Link)
        link.unit_id = 1
        link.locked_addr = ("127.0.0.1", 4210)
        link.sock = Socket()
        link._lock = __import__("threading").Lock()
        link._seq = 0
        link._send_times = {}
        link._send_order = __import__("collections").deque()
        link.tx_count = 0
        link.send(0.4, 0.8, True, 1.0, servo_calibration=True)
        control = proto.parse_control(link.sock.packets[0][0])
        self.assertIsNotNone(control)
        self.assertEqual(control.flags, proto.FLAG_SERVO_CALIBRATION)
        self.assertFalse(control.armed)
        self.assertEqual(control.throttle, 0)
        self.assertEqual(control.brake, 0)
        self.assertEqual(control.steer, 400)

    def test_config_save_validates_and_preserves_yaml_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("steering:\n  trim: 0.0\n\nthrottle:\n  deadzone: 0.1\n", encoding="utf-8")
            cfg.save_servo_calibration(-0.8, 0.1, 0.9, path)
            loaded = cfg.load_config(path)
            self.assertEqual(loaded["steering"]["servo_left"], -0.8)
            self.assertEqual(loaded["steering"]["servo_center"], 0.1)
            self.assertEqual(loaded["steering"]["servo_right"], 0.9)
            with self.assertRaises(ValueError):
                cfg.save_servo_calibration(0.0, -0.1, 1.0, path)


if __name__ == "__main__":
    unittest.main()
