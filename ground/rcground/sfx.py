"""Stateful ground-station engine and horn feedback.

Audio is deliberately isolated from control: a missing mixer, asset, or
speaker leaves the engine as a safe no-op and never interrupts UDP control.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional until requirements installed
    yaml = None  # type: ignore[assignment]

try:
    import pygame
except ImportError:  # pragma: no cover - optional in headless test runners
    pygame = None  # type: ignore[assignment]

CATEGORIES = ("gas", "horn", "arm")
OFF = "OFF"
STARTING = "STARTING"
IDLE = "IDLE"
REVVING = "REVVING"
DECELERATING = "DECELERATING"
RPM_IDLE = 0.16
RPM_ATTACK = 5.5
RPM_RELEASE = 2.4
IDLE_VOLUME = 0.82
REV_VOLUME = 0.98
HORN_VOLUME = 1.0


def _sfx_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets" / "sfx"
    return Path(__file__).resolve().parent.parent / "assets" / "sfx"


class _Pack:
    __slots__ = ("sound", "title", "filename", "profile", "layer")

    def __init__(
        self, sound, title: str, filename: str = "", profile: str | None = None,
        layer: int | None = None,
    ) -> None:
        self.sound = sound
        self.title = title
        self.filename = filename
        self.profile = profile
        self.layer = layer


class SfxEngine:
    """Engine idle/rev crossfader with a short ignition transition."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = False
        self._packs: dict[str, list[_Pack]] = {c: [] for c in CATEGORIES}
        self._index: dict[str, int] = {c: 0 for c in CATEGORIES}
        self._channel_idle = None
        self._channel_rev = None
        self._channel_horn = None
        self._channel_arm = None
        self._idle_pack = None
        self._rev_pack = None
        self._played_idle = None
        self._played_rev = None
        self._state = OFF
        self._virtual_rpm = 0.0
        self._horn_active = False
        self._horn_pack = None

        if not enabled:
            return
        if pygame is None:
            print("SFX: modul pygame tidak tersedia, suara dimatikan.")
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._load_all()
            if not any(self._packs.values()):
                print("SFX: tidak ada berkas suara termuat, suara dimatikan.")
                return
            # Separate channels let horn dominate while overlapping engine audio.
            self._channel_idle = pygame.mixer.Channel(0)
            self._channel_rev = pygame.mixer.Channel(1)
            self._channel_horn = pygame.mixer.Channel(2)
            self._channel_arm = pygame.mixer.Channel(3)
        except Exception as exc:  # noqa: BLE001
            print(f"SFX: gagal menyiapkan audio ({exc}), suara dimatikan.")
            self._packs = {c: [] for c in CATEGORIES}
            return
        self._enabled = True

    @property
    def state(self) -> str:
        return self._state

    @property
    def virtual_rpm(self) -> float:
        return self._virtual_rpm

    @property
    def horn_active(self) -> bool:
        return self._horn_active

    def _load_all(self) -> None:
        if yaml is None:
            raise RuntimeError("PyYAML tidak tersedia")
        root = _sfx_root()
        with (root / "manifest.yaml").open("r", encoding="utf-8") as handle:
            manifest = yaml.safe_load(handle) or {}
        for category in CATEGORIES:
            packs: list[_Pack] = []
            for entry in manifest.get(category) or []:
                filename = entry.get("file")
                if not filename:
                    continue
                try:
                    sound = pygame.mixer.Sound(str(root / category / filename))
                except Exception as exc:  # noqa: BLE001
                    print(f"SFX: gagal memuat {filename} ({exc}), dilewati.")
                    continue
                layer = entry.get("rpm_layer")
                try:
                    layer = int(layer) if layer is not None else None
                except (TypeError, ValueError):
                    layer = None
                packs.append(
                    _Pack(
                        sound,
                        entry.get("title", filename),
                        filename,
                        entry.get("profile"),
                        layer,
                    )
                )
            self._packs[category] = packs

    def _clamp_index(self, category: str) -> None:
        packs = self._packs.get(category, [])
        self._index[category] = self._index.get(category, 0) % len(packs) if packs else 0

    def set_pack(self, category: str, index: int) -> None:
        if category in self._packs:
            try:
                self._index[category] = int(index)
            except (TypeError, ValueError):
                self._index[category] = 0
            self._clamp_index(category)

    def next_pack(self, category: str) -> None:
        if category in self._packs and self._packs[category]:
            self._index[category] += 1
            self._clamp_index(category)

    def prev_pack(self, category: str) -> None:
        if category in self._packs and self._packs[category]:
            self._index[category] -= 1
            self._clamp_index(category)

    def pack_index(self, category: str) -> int:
        return self._index.get(category, 0)

    def pack_label(self, category: str) -> str:
        packs = self._packs.get(category, [])
        if not packs:
            return "-- (tidak ada)"
        index = self._index.get(category, 0) % len(packs)
        return f"{index + 1}/{len(packs)} {packs[index].title}"

    def _current(self, category: str):
        packs = self._packs.get(category, [])
        return packs[self._index.get(category, 0) % len(packs)] if packs else None

    def _find_idle_pack(self):
        for pack in self._packs.get("gas", []):
            if "idle" in pack.filename.lower() or "idle" in pack.title.lower():
                return pack
        return self._current("gas")

    def _profile_layers(self, pack):
        if pack is None or not pack.profile:
            return []
        return sorted(
            (
                candidate
                for candidate in self._packs.get("gas", [])
                if candidate.profile == pack.profile and candidate.layer is not None
            ),
            key=lambda candidate: candidate.layer,
        )

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _stop(channel, fade_ms: int = 0) -> None:
        if channel is None:
            return
        try:
            if fade_ms > 0:
                channel.fadeout(fade_ms)
            else:
                channel.stop()
        except Exception:
            pass

    @staticmethod
    def _play_loop(channel, pack, previous_pack) -> bool:
        if channel is None or pack is None:
            return False
        try:
            if pack is not previous_pack or not channel.get_busy():
                channel.stop()
                channel.play(pack.sound, loops=-1)
            return True
        except Exception:
            return False

    def start_engine(self) -> None:
        """Start ignition once, then maintain a running idle loop."""
        if not self._enabled or self._state != OFF:
            return
        self._virtual_rpm = RPM_IDLE
        self._idle_pack = self._find_idle_pack()
        self._rev_pack = self._current("gas")
        self._state = STARTING
        pack = self._current("arm")
        try:
            if pack is not None and self._channel_arm is not None:
                self._channel_arm.stop()
                self._channel_arm.play(pack.sound)
            else:
                self._state = IDLE
        except Exception:
            self._state = IDLE

    def play_arm(self) -> None:
        self.start_engine()

    def update(self, dt: float, intensity: float, active: bool) -> None:
        """Advance RPM smoothing and engine crossfade once per control tick."""
        if not self._enabled:
            return
        if not active:
            self.stop_engine(fast=True)
            return
        if self._state == OFF:
            self.start_engine()
        dt = max(0.0, min(0.25, float(dt)))
        target = RPM_IDLE + self._clamp(float(intensity)) * (1.0 - RPM_IDLE)
        previous_rpm = self._virtual_rpm
        rate = RPM_ATTACK if target > self._virtual_rpm else RPM_RELEASE
        self._virtual_rpm += (target - self._virtual_rpm) * min(1.0, rate * dt)

        if self._state == STARTING and self._channel_arm is not None:
            try:
                if not self._channel_arm.get_busy():
                    self._state = IDLE
                else:
                    # Ignition owns the foreground transition. Do not start
                    # idle/rev loops underneath it or they will mask the
                    # startup sound.
                    return
            except Exception:
                self._state = IDLE
        if self._state != STARTING:
            if self._virtual_rpm <= RPM_IDLE + 0.01:
                self._state = IDLE
            elif target < previous_rpm - 0.01:
                self._state = DECELERATING
            else:
                self._state = REVVING

        if not self._enabled:
            return
        self._idle_pack = self._find_idle_pack()
        self._rev_pack = self._current("gas")
        mix = self._clamp((self._virtual_rpm - RPM_IDLE) / (1.0 - RPM_IDLE))
        layers = self._profile_layers(self._rev_pack)
        if layers:
            # Only adjacent RPM layers are active. The lower layer is held on
            # the idle channel and the upper layer on the rev channel.
            position = mix * (len(layers) - 1)
            lower_index = min(len(layers) - 1, int(position))
            fraction = position - lower_index
            upper_index = (
                lower_index
                if fraction <= 1e-6
                else min(len(layers) - 1, lower_index + 1)
            )
            lower = layers[lower_index]
            upper = layers[upper_index]
            self._play_loop(self._channel_idle, lower, self._played_idle)
            self._played_idle = lower
            if upper is lower:
                self._stop(self._channel_rev)
                self._played_rev = None
            else:
                self._play_loop(self._channel_rev, upper, self._played_rev)
                self._played_rev = upper
            try:
                self._channel_idle.set_volume(IDLE_VOLUME * (1.0 - fraction))
                self._channel_rev.set_volume(REV_VOLUME * fraction)
            except Exception:
                pass
            return

        self._play_loop(self._channel_idle, self._idle_pack, self._played_idle)
        self._played_idle = self._idle_pack
        self._play_loop(self._channel_rev, self._rev_pack, self._played_rev)
        self._played_rev = self._rev_pack
        try:
            self._channel_idle.set_volume(IDLE_VOLUME * (1.0 - 0.82 * mix))
            self._channel_rev.set_volume(REV_VOLUME * mix)
        except Exception:
            pass

    def update_gas(self, intensity: float, active: bool, dt: float = 1.0 / 60.0) -> None:
        self.update(dt, intensity, active)

    def stop_engine(self, fast: bool = False) -> None:
        if self._state == OFF and self._virtual_rpm == 0.0:
            return
        fade_ms = 40 if fast else 160
        self._stop(self._channel_idle, fade_ms)
        self._stop(self._channel_rev, fade_ms)
        self._stop(self._channel_arm, fade_ms)
        self._virtual_rpm = 0.0
        self._state = OFF
        self._played_idle = None
        self._played_rev = None

    def update_horn(self, held: bool) -> None:
        """Hold the horn while input is held; do not restart each frame."""
        if not self._enabled:
            return
        held = bool(held)
        if held and not self._horn_active:
            self._horn_active = True
            self._horn_pack = self._current("horn")
            if self._enabled and self._horn_pack is not None:
                try:
                    self._channel_horn.stop()
                    self._channel_horn.play(self._horn_pack.sound, loops=-1)
                    self._channel_horn.set_volume(HORN_VOLUME)
                except Exception:
                    pass
        elif not held and self._horn_active:
            self._horn_active = False
            self._stop(self._channel_horn, 50)
            self._horn_pack = None

    def play_horn(self) -> None:
        self.update_horn(True)
