"""Deterministic SFX state tests; no speaker or pygame mixer required."""

from __future__ import annotations

import unittest

from rcground.sfx import DECELERATING, IDLE, OFF, REVVING, STARTING, SfxEngine, _Pack


class DummyChannel:
    def __init__(self, busy: bool = False):
        self.busy = busy
        self.play_calls = 0
        self.stop_calls = 0
        self.fade_calls = []
        self.volumes = []

    def get_busy(self):
        return self.busy

    def play(self, sound, loops=0):
        self.play_calls += 1
        self.busy = True

    def stop(self):
        self.stop_calls += 1
        self.busy = False

    def fadeout(self, ms):
        self.fade_calls.append(ms)
        self.busy = False

    def set_volume(self, value):
        self.volumes.append(value)


def make_engine() -> SfxEngine:
    engine = SfxEngine.__new__(SfxEngine)
    engine._enabled = True
    sound = object()
    gas = _Pack(sound, "rev", "sports_car_accel_fast.mp3")
    idle = _Pack(sound, "idle", "rally_car_idle_loop.mp3")
    horn = _Pack(sound, "horn", "car_horn.mp3")
    arm = _Pack(sound, "start", "car_engine_start.mp3")
    engine._packs = {"gas": [gas, idle], "horn": [horn], "arm": [arm]}
    engine._index = {"gas": 0, "horn": 0, "arm": 0}
    engine._channel_idle = DummyChannel()
    engine._channel_rev = DummyChannel()
    engine._channel_horn = DummyChannel()
    engine._channel_arm = DummyChannel()
    engine._idle_pack = engine._rev_pack = engine._played_idle = engine._played_rev = None
    engine._state = OFF
    engine._virtual_rpm = 0.0
    engine._horn_active = False
    engine._horn_pack = None
    return engine


class SfxStateTests(unittest.TestCase):
    def test_ignition_finishes_before_engine_loops_start(self):
        engine = make_engine()
        engine.start_engine()
        engine.update(0.1, 0.0, True)
        self.assertEqual(engine.state, STARTING)
        self.assertEqual(engine._channel_idle.play_calls, 0)
        self.assertEqual(engine._channel_rev.play_calls, 0)
        engine._channel_arm.busy = False
        engine.update(0.1, 0.0, True)
        self.assertEqual(engine.state, IDLE)
        self.assertGreater(engine._channel_idle.play_calls, 0)
        self.assertGreater(engine._channel_rev.play_calls, 0)

    def test_engine_starts_idle_then_revs_and_decelerates(self):
        engine = make_engine()
        engine.start_engine()
        self.assertEqual(engine.state, STARTING)
        engine._channel_arm.busy = False
        engine.update(0.05, 0.0, True)
        self.assertEqual(engine.state, IDLE)

    def test_profile_keeps_only_adjacent_layers_active(self):
        engine = make_engine()
        layers = [
            _Pack(object(), f"layer {index}", f"layer{index}.wav", "sportscar_cc0", index)
            for index in range(4)
        ]
        engine._packs["gas"] = layers
        engine.start_engine()
        engine._channel_arm.busy = False
        engine.update(0.05, 0.0, True)
        self.assertGreater(engine._channel_idle.play_calls, 0)
        self.assertEqual(engine._channel_rev.play_calls, 0)
        engine.update(0.05, 0.5, True)
        self.assertLessEqual(engine._channel_idle.play_calls, 2)
        self.assertLessEqual(engine._channel_rev.play_calls, 1)
        self.assertGreater(engine._channel_idle.play_calls, 0)
        engine.update(0.2, 1.0, True)
        self.assertEqual(engine.state, REVVING)
        plays = engine._channel_rev.play_calls
        engine.update(0.05, 1.0, True)
        self.assertEqual(engine._channel_rev.play_calls, plays)
        engine.update(0.1, 0.0, True)
        self.assertEqual(engine.state, DECELERATING)
        for _ in range(20):
            engine.update(0.1, 0.0, True)
        self.assertEqual(engine.state, IDLE)

    def test_disarm_fades_and_horn_is_level_triggered(self):
        engine = make_engine()
        engine.start_engine()
        engine.update(0.1, 0.5, True)
        engine.update_horn(True)
        engine.update_horn(True)
        self.assertEqual(engine._channel_horn.play_calls, 1)
        engine.update_horn(False)
        self.assertFalse(engine.horn_active)
        engine.stop_engine()
        self.assertEqual(engine.state, OFF)
        self.assertTrue(engine._channel_idle.fade_calls)

    def test_disabled_engine_remains_safe_noop(self):
        engine = SfxEngine(enabled=False)
        engine.start_engine()
        engine.update(0.1, 1.0, True)
        engine.update_horn(True)
        self.assertEqual(engine.state, OFF)
        self.assertEqual(engine.virtual_rpm, 0.0)
        self.assertFalse(engine.horn_active)
        engine.stop_engine(fast=True)
        self.assertEqual(engine.state, OFF)


if __name__ == "__main__":
    unittest.main()
