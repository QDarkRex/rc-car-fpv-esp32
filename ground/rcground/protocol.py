"""Struktur paket UDP RC Car v3.

KEMBAR dengan: firmware/rc_car_esp32/protocol.h  dan  docs/protocol.md
Kalau salah satu diubah, ubah ketiganya.

v3 menambah field unit_id ke kedua paket, supaya 3 mobil bisa berbagi satu
jaringan tanpa saling mengunci silang. Lihat docs/protocol.md bagian 7.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 3
CONTROL_PORT = 4210

CTRL_MAGIC = b"RC"
TELE_MAGIC = b"RT"

# Flag paket kontrol
FLAG_ARMED = 0x01
FLAG_SERVO_CALIBRATION = 0x02  # steering-only, must remain disarmed/netral

# Flag paket telemetri
TFLAG_ARMED = 0x01
TFLAG_FAILSAFE = 0x02
TFLAG_LOWBATT = 0x04

# Rentang nilai kendali yang dikirim di kabel
AXIS_MAX = 1000

# '<' = little-endian DAN tanpa padding. Keduanya wajib agar cocok
# dengan struct #pragma pack(1) di sisi ESP32.
_CTRL_FMT = "<BBBBHBhhB"     # tanpa crc; crc ditambahkan terpisah
_TELE_FMT = "<BBBBHHbBI"     # tanpa crc

CONTROL_SIZE = struct.calcsize(_CTRL_FMT) + 1   # 13
TELEMETRY_SIZE = struct.calcsize(_TELE_FMT) + 1  # 15

assert CONTROL_SIZE == 13, f"ControlPacket harus 13 byte, dapat {CONTROL_SIZE}"
assert TELEMETRY_SIZE == 15, f"TelemetryPacket harus 15 byte, dapat {TELEMETRY_SIZE}"


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
    unit_id: int    # 1..3, mobil mana yang dituju
    seq: int
    flags: int
    steer: int      # -1000..1000
    throttle: int   # -1000..1000
    brake: int      # 0..255, 0 = tidak mengerem

    @property
    def armed(self) -> bool:
        return bool(self.flags & FLAG_ARMED)

    @property
    def servo_calibration(self) -> bool:
        return bool(self.flags & FLAG_SERVO_CALIBRATION)


@dataclass(frozen=True)
class Telemetry:
    unit_id: int    # mobil mana yang mengirim
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
    unit_id: int, seq: int, flags: int, steer: int, throttle: int, brake: int = 0
) -> bytes:
    body = struct.pack(
        _CTRL_FMT,
        CTRL_MAGIC[0],
        CTRL_MAGIC[1],
        PROTOCOL_VERSION,
        unit_id & 0xFF,
        seq & 0xFFFF,
        flags & 0xFF,
        _clamp_axis(steer),
        _clamp_axis(throttle),
        max(0, min(255, int(brake))),
    )
    return body + bytes([crc8(body)])


def parse_control(data: bytes) -> Control | None:
    """Kembalikan Control, atau None bila paket tidak valid (dibuang diam-diam).

    CATATAN: ini HANYA memvalidasi bentuk paket (panjang, magic, versi, CRC).
    Penyaringan unit_id -- membuang paket yang bukan untuk mobil ini -- adalah
    tanggung jawab pemanggil, persis seperti di firmware. Lihat
    docs/protocol.md bagian 7 untuk alasannya.
    """
    if len(data) != CONTROL_SIZE:
        return None
    if data[0:2] != CTRL_MAGIC or data[2] != PROTOCOL_VERSION:
        return None
    if crc8(data[:-1]) != data[-1]:
        return None
    _, _, _, unit_id, seq, flags, steer, throttle, brake = struct.unpack(
        _CTRL_FMT, data[:-1]
    )
    return Control(
        unit_id=unit_id, seq=seq, flags=flags, steer=steer, throttle=throttle, brake=brake
    )


def pack_telemetry(
    unit_id: int, seq_echo: int, vbat_mv: int, rssi: int, flags: int, uptime_ms: int
) -> bytes:
    body = struct.pack(
        _TELE_FMT,
        TELE_MAGIC[0],
        TELE_MAGIC[1],
        PROTOCOL_VERSION,
        unit_id & 0xFF,
        seq_echo & 0xFFFF,
        max(0, min(65535, int(vbat_mv))),
        max(-128, min(127, int(rssi))),
        flags & 0xFF,
        uptime_ms & 0xFFFFFFFF,
    )
    return body + bytes([crc8(body)])


def parse_telemetry(data: bytes) -> Telemetry | None:
    """Kembalikan Telemetry, atau None bila paket tidak valid.

    Sama seperti parse_control(): hanya memvalidasi bentuk paket. Penyaringan
    unit_id adalah tanggung jawab pemanggil (lihat rcground/link.py).
    """
    if len(data) != TELEMETRY_SIZE:
        return None
    if data[0:2] != TELE_MAGIC or data[2] != PROTOCOL_VERSION:
        return None
    if crc8(data[:-1]) != data[-1]:
        return None
    _, _, _, unit_id, seq_echo, vbat_mv, rssi, flags, uptime = struct.unpack(
        _TELE_FMT, data[:-1]
    )
    return Telemetry(
        unit_id=unit_id,
        seq_echo=seq_echo,
        vbat_mv=vbat_mv,
        rssi=rssi,
        flags=flags,
        uptime_ms=uptime,
    )
