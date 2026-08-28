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

# ------------------------------------------------------------------ video UDP
#
# Protokol TERPISAH dari kendali, di port sendiri. Kembar dengan
# firmware/rc_cam_esp32_udp/.
#
# KENAPA UDP UNTUK VIDEO, padahal HTTP/TCP sudah bekerja:
#
# Pada TCP, satu segmen hilang menahan SELURUH aliran sampai kiriman
# ulangnya sampai -- video membeku, lalu frame menumpuk datang serentak.
# Itulah "patah-patah" yang dikeluhkan, dan di 2,4 GHz yang padat paket
# hilang adalah kejadian normal, bukan kelainan.
#
# UDP tidak punya kiriman ulang dan tidak menjamin urutan. Fragmen yang
# hilang berarti SATU frame tidak lengkap lalu dibuang -- frame berikutnya
# tetap datang tepat waktu. Untuk FPV itu pertukaran yang jelas
# menguntungkan: gambar yang hilang sekejap jauh lebih baik daripada
# seluruh aliran membeku.
#
# TIDAK ADA CRC di paket video, berbeda dengan paket kendali. UDP sudah
# membawa checksum-nya sendiri dan lwIP di ESP32 menghitungnya, jadi paket
# rusak sudah dibuang tumpukan jaringan sebelum sampai ke kita. Menambah
# CRC8 di sini hanya membebani ESP32 pada setiap fragmen tanpa menangkap
# apa pun yang belum tertangkap.
VIDEO_PORT = 4211

VIDEO_MAGIC = b"RV"     # fragmen video, kamera -> darat
SUBSCRIBE_MAGIC = b"RS"  # permintaan stream, darat -> kamera

# Muatan maksimum per fragmen. 1400 + 10 byte header = 1410, aman di bawah
# MTU 1500 dikurangi header IP (20) dan UDP (8) = 1472. Sengaja tidak
# dipepet ke batas: jaringan dengan MTU lebih kecil (VPN, beberapa AP)
# akan memfragmentasi di lapisan IP, dan fragmen IP yang hilang membuang
# seluruh datagram -- persis yang ingin dihindari.
VIDEO_PAYLOAD_MAX = 1400

_VIDEO_FMT = "<BBBBHBBH"           # magic, magic, versi, unit, frame, idx, cnt, len
VIDEO_HEADER_SIZE = struct.calcsize(_VIDEO_FMT)

_SUBSCRIBE_FMT = "<BBBB"
SUBSCRIBE_SIZE = struct.calcsize(_SUBSCRIBE_FMT)

assert VIDEO_HEADER_SIZE == 10, f"header video harus 10 byte, dapat {VIDEO_HEADER_SIZE}"
assert SUBSCRIBE_SIZE == 4, f"paket subscribe harus 4 byte, dapat {SUBSCRIBE_SIZE}"

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


@dataclass(frozen=True)
class VideoFragment:
    unit_id: int
    frame_id: int    # naik tiap frame, membungkus di 65535
    index: int       # 0-based
    count: int       # total fragmen frame ini
    payload: bytes


def pack_video(
    unit_id: int, frame_id: int, index: int, count: int, payload: bytes
) -> bytes:
    if len(payload) > VIDEO_PAYLOAD_MAX:
        raise ValueError(
            f"muatan fragmen {len(payload)} melebihi {VIDEO_PAYLOAD_MAX}"
        )
    header = struct.pack(
        _VIDEO_FMT,
        VIDEO_MAGIC[0],
        VIDEO_MAGIC[1],
        PROTOCOL_VERSION,
        unit_id & 0xFF,
        frame_id & 0xFFFF,
        index & 0xFF,
        count & 0xFF,
        len(payload),
    )
    return header + payload


def parse_video(data: bytes) -> VideoFragment | None:
    """Kembalikan VideoFragment, atau None bila paket tidak valid.

    Sama seperti parse_control(): hanya memvalidasi BENTUK paket.
    Penyaringan unit_id adalah tanggung jawab pemanggil, supaya kamera unit
    lain yang kebetulan terdengar tidak pernah ikut membentuk frame di sini.
    """
    if len(data) < VIDEO_HEADER_SIZE:
        return None
    if data[0:2] != VIDEO_MAGIC or data[2] != PROTOCOL_VERSION:
        return None
    _, _, _, unit_id, frame_id, index, count, length = struct.unpack(
        _VIDEO_FMT, data[:VIDEO_HEADER_SIZE]
    )
    # count 0 tidak masuk akal, dan index di luar count berarti paket rusak
    # atau dari versi lain -- dibuang tanpa efek, seperti paket kendali cacat.
    if count == 0 or index >= count:
        return None
    payload = data[VIDEO_HEADER_SIZE:]
    if len(payload) != length:
        return None
    return VideoFragment(
        unit_id=unit_id, frame_id=frame_id, index=index, count=count, payload=payload
    )


def pack_subscribe(unit_id: int) -> bytes:
    """Permintaan agar kamera mulai/terus mengirim ke alamat pengirim.

    Dikirim berkala oleh sisi darat, bukan sekali saja: kamera berhenti
    mengirim kalau permintaan berhenti datang, sehingga kamera yang
    ditinggalkan tidak terus membanjiri jaringan -- itu penting justru
    karena UDP tidak punya mekanisme backpressure seperti TCP.
    """
    return struct.pack(
        _SUBSCRIBE_FMT,
        SUBSCRIBE_MAGIC[0],
        SUBSCRIBE_MAGIC[1],
        PROTOCOL_VERSION,
        unit_id & 0xFF,
    )


def parse_subscribe(data: bytes) -> int | None:
    """Kembalikan unit_id yang diminta, atau None bila paket tidak valid."""
    if len(data) != SUBSCRIBE_SIZE:
        return None
    if data[0:2] != SUBSCRIBE_MAGIC or data[2] != PROTOCOL_VERSION:
        return None
    return data[3]


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
