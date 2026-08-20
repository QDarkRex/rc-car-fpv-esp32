// protocol.h — struktur paket UDP RC Car v2
//
// KEMBAR dengan: ground/rcground/protocol.py  dan  docs/protocol.md
// Kalau salah satu diubah, ubah ketiganya.

#pragma once
#include <stdint.h>
#include <stddef.h>

#define RC_PROTOCOL_VERSION 2
#define RC_CONTROL_PORT     4210

// Magic
#define RC_CTRL_MAGIC0 'R'
#define RC_CTRL_MAGIC1 'C'
#define RC_TELE_MAGIC0 'R'
#define RC_TELE_MAGIC1 'T'

// Flag paket kontrol
#define RC_FLAG_ARMED     0x01

// Flag paket telemetri
#define RC_TFLAG_ARMED    0x01
#define RC_TFLAG_FAILSAFE 0x02
#define RC_TFLAG_LOWBATT  0x04

// Rentang nilai kendali
#define RC_AXIS_MAX 1000

// Telemetri dibalas pada tiap paket kontrol ke-N, bukan dari timer bebas.
// Pada laju kontrol 50 Hz, N=5 menghasilkan tepat 10 Hz -- dan membuat angka
// RTT di HUD menjadi waktu tempuh sungguhan. Lihat docs/protocol.md bagian 3.
#define RC_TELEMETRY_EVERY_N 5

#pragma pack(push, 1)

struct ControlPacket {
  uint8_t  magic0;
  uint8_t  magic1;
  uint8_t  version;
  uint16_t seq;
  uint8_t  flags;
  int16_t  steer;      // -1000..1000, negatif = kiri
  int16_t  throttle;   // -1000..1000, negatif = mundur
  uint8_t  brake;       // 0..255, 0 = tidak mengerem
  uint8_t  crc;
};

struct TelemetryPacket {
  uint8_t  magic0;
  uint8_t  magic1;
  uint8_t  version;
  uint16_t seq_echo;
  uint16_t vbat_mv;
  int8_t   rssi;
  uint8_t  flags;
  uint32_t uptime_ms;
  uint8_t  crc;
};

#pragma pack(pop)

static_assert(sizeof(ControlPacket) == 12, "ControlPacket harus 12 byte");
static_assert(sizeof(TelemetryPacket) == 14, "TelemetryPacket harus 14 byte");

// CRC-8/ATM: poly 0x07, init 0x00, tanpa refleksi, tanpa xorout.
inline uint8_t rc_crc8(const uint8_t *data, size_t len) {
  uint8_t crc = 0;
  while (len--) {
    crc ^= *data++;
    for (uint8_t i = 0; i < 8; i++)
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  }
  return crc;
}

// Validasi lengkap paket kontrol. Mengembalikan true hanya bila panjang,
// magic, versi, dan CRC semuanya benar.
inline bool rc_validate_control(const uint8_t *buf, size_t len) {
  if (len != sizeof(ControlPacket)) return false;
  if (buf[0] != RC_CTRL_MAGIC0 || buf[1] != RC_CTRL_MAGIC1) return false;
  if (buf[2] != RC_PROTOCOL_VERSION) return false;
  return rc_crc8(buf, sizeof(ControlPacket) - 1) == buf[sizeof(ControlPacket) - 1];
}

// Isi field crc pada paket telemetri yang sudah terisi field lainnya.
inline void rc_finalize_telemetry(TelemetryPacket *t) {
  t->crc = rc_crc8((const uint8_t *)t, sizeof(TelemetryPacket) - 1);
}
