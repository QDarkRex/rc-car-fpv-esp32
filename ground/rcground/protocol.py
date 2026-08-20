"""Struktur paket UDP RC Car v2.

KEMBAR dengan: firmware/rc_car_esp32/protocol.h  dan  docs/protocol.md
Kalau salah satu diubah, ubah ketiganya.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 2
CONTROL_PORT = 4210

CTRL_MAGIC = b"RC"
TELE_MAGIC = b"RT"

# Flag paket kontrol
FLAG_ARMED = 0x01

# Flag paket telemetri
TFLAG_ARMED = 0x01
TFLAG_FAILSAFE = 0x02
TFLAG_LOWBATT = 0x04

# Rentang nilai kendali yang dikirim di kabel
AXIS_MAX = 1000

# '<' = little-endian DAN tanpa padding. Keduanya wajib agar cocok
# dengan struct #pragma pack(1) di sisi ESP32.
_CTRL_FMT = "<BBBHBhhB"     # tanpa crc; crc ditambahkan terpisah
_TELE_FMT = "<BBBHHbBI"     # tanpa crc

CONTROL_SIZE = struct.calcsize(_CTRL_FMT) + 1   # 12
TELEMETRY_SIZE = struct.calcsize(_TELE_FMT) + 1  # 14

assert CONTROL_SIZE == 12, f"ControlPacket harus 12 byte, dapat {CONTROL_SIZE}"
assert TELEMETRY_SIZE == 14, f"TelemetryPacket harus 14 byte, dapat {TELEMETRY_SIZE}"


def crc8(data: bytes) -> int:
    """CRC-8/ATM: poly 0x07, init 0x00, tanpa refleksi, tanpa xorout."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


@dataclass(frozen=True)
class Control:
    seq: int
    flags: int
    steer: int      # -1000..1000
    throttle: int   # -1000..1000
    brake: int      # 0..255, 0 = tidak mengerem

    @property
    def armed(self) -> bool:
        return bool(self.flags & FLAG_ARMED)


@dataclass(frozen=True)
class Telemetry:
    seq_echo: int
    vbat_mv: int
    rssi: int
    flags: int
    uptime_ms: int

    @property
    def armed(self) -> bool:
        return bool(self.flags & TFLAG_ARMED)

    @property
    def failsafe(self) -> bool:
        return bool(self.flags & TFLAG_FAILSAFE)

    @property
    def low_batt(self) -> bool:
        return bool(self.flags & TFLAG_LOWBATT)

    @property
    def vbat(self) -> float:
        return self.vbat_mv / 1000.0


def _clamp_axis(value: int) -> int:
    return max(-AXIS_MAX, min(AXIS_MAX, int(value)))


def pack_control(
    seq: int, flags: int, steer: int, throttle: int, brake: int = 0
) -> bytes:
    body = struct.pack(
        _CTRL_FMT,
        CTRL_MAGIC[0],
        CTRL_MAGIC[1],
        PROTOCOL_VERSION,
        seq & 0xFFFF,
        flags & 0xFF,
        _clamp_axis(steer),
        _clamp_axis(throttle),
        max(0, min(255, int(brake))),
    )
    return body + bytes([crc8(body)])


def parse_control(data: bytes) -> Control | None:
    """Kembalikan Control, atau None bila paket tidak valid (dibuang diam-diam)."""
    if len(data) != CONTROL_SIZE:
        return None
    if data[0:2] != CTRL_MAGIC or data[2] != PROTOCOL_VERSION:
        return None
    if crc8(data[:-1]) != data[-1]:
        return None
    _, _, _, seq, flags, steer, throttle, brake = struct.unpack(_CTRL_FMT, data[:-1])
    return Control(seq=seq, flags=flags, steer=steer, throttle=throttle, brake=brake)


def pack_telemetry(
    seq_echo: int, vbat_mv: int, rssi: int, flags: int, uptime_ms: int
) -> bytes:
    body = struct.pack(
        _TELE_FMT,
        TELE_MAGIC[0],
        TELE_MAGIC[1],
        PROTOCOL_VERSION,
        seq_echo & 0xFFFF,
        max(0, min(65535, int(vbat_mv))),
        max(-128, min(127, int(rssi))),
        flags & 0xFF,
        uptime_ms & 0xFFFFFFFF,
    )
    return body + bytes([crc8(body)])


def parse_telemetry(data: bytes) -> Telemetry | None:
    """Kembalikan Telemetry, atau None bila paket tidak valid."""
    if len(data) != TELEMETRY_SIZE:
        return None
    if data[0:2] != TELE_MAGIC or data[2] != PROTOCOL_VERSION:
        return None
    if crc8(data[:-1]) != data[-1]:
        return None
    _, _, _, seq_echo, vbat_mv, rssi, flags, uptime = struct.unpack(_TELE_FMT, data[:-1])
    return Telemetry(
        seq_echo=seq_echo, vbat_mv=vbat_mv, rssi=rssi, flags=flags, uptime_ms=uptime
    )
