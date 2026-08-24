"""Fake-car model tests for the steering-only calibration flag."""

from __future__ import annotations

import socket
import unittest

from fake_car import FakeCar
from rcground import protocol as proto


class FakeCalibrationTests(unittest.TestCase):
    def _send(self, car, flags, steer, throttle=0, brake=0):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packet = proto.pack_control(1, 1, flags, steer, throttle, brake)
            sender.sendto(packet, ("127.0.0.1", car.sock.getsockname()[1]))
            car.poll()
        finally:
            sender.close()

    def test_valid_calibration_moves_only_steering(self):
        car = FakeCar(0, 0.0, 1)
        try:
            self._send(car, proto.FLAG_SERVO_CALIBRATION, 500)
            car.update(0.01)
            self.assertTrue(car.servo_calibration)
            self.assertEqual(car.applied_steer, 500)
            self.assertFalse(car.armed)
            self.assertEqual(car.applied_throttle, 0)
        finally:
            car.sock.close()

    def test_invalid_calibration_cannot_apply_motor_or_calibration_steer(self):
        car = FakeCar(0, 0.0, 1)
        try:
            self._send(car, proto.FLAG_SERVO_CALIBRATION, 500, throttle=1)
            car.update(0.01)
            self.assertFalse(car.servo_calibration)
            self.assertEqual(car.applied_steer, 0)
            self.assertFalse(car.armed)
            self.assertEqual(car.applied_throttle, 0)
        finally:
            car.sock.close()

    def test_normal_armed_packet_still_applies_steering(self):
        car = FakeCar(0, 0.0, 1)
        try:
            self._send(car, proto.FLAG_ARMED, 400, throttle=250)
            car.update(0.01)
            self.assertFalse(car.servo_calibration)
            self.assertTrue(car.armed)
            self.assertEqual(car.applied_steer, 400)
            self.assertEqual(car.applied_throttle, 250)
        finally:
            car.sock.close()


if __name__ == "__main__":
    unittest.main()
