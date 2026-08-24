// link.h — WiFi, UDP, failsafe, arming, dan telemetri.
//
// Kelas ini memegang seluruh logika keselamatan tautan. Aturannya ditulis
// lengkap di docs/protocol.md bagian 5 -- baca dulu sebelum mengubah apa pun
// di sini, terutama bagian penguncian prevArmedFlag.

#pragma once

#include <Arduino.h>
#include <WiFiUdp.h>
#include <stdint.h>

#include "config.h"
#include "protocol.h"

class CarLink {
 public:
  void begin();
  void update();

  // Perintah terakhir yang sah. Saat failsafe atau disarmed, semuanya nol --
  // rem TIDAK dikecualikan dari aturan ini. Pengereman hanya boleh terjadi
  // atas perintah pengemudi; failsafe dan disarm tetap memakai coast() di
  // Drive, bukan mengerem otomatis (lihat komentar coast() di drive.cpp).
  int16_t steer() const { return _armed ? _steer : 0; }
  int16_t servoCalibrationSteer() const {
    return _servoCalibration ? _servoSteer : 0;
  }
  int16_t throttle() const { return _armed ? _throttle : 0; }
  uint8_t brake() const { return _armed ? _brake : 0; }

  bool armed() const { return _armed; }
  bool servoCalibration() const { return _servoCalibration && !_failsafe && !_armed; }
  bool failsafe() const { return _failsafe; }
  bool wifiConnected() const { return _wifiConnected; }
  uint16_t vbatMv() const { return _vbatMv; }
  bool lowBattery() const { return _vbatMv > 0 && _vbatMv < VBAT_LOW_MV; }

  uint32_t rxCount() const { return _rxCount; }
  uint32_t badCount() const { return _badCount; }
  uint32_t staleCount() const { return _staleCount; }
  // Paket kontrol valid (magic/versi/CRC benar) tapi unit_id-nya bukan
  // milik mobil ini -- lihat docs/protocol.md bagian 7. Dipisah dari
  // badCount supaya "status" di konsol bisa membedakan paket rusak dari
  // paket sehat yang memang bukan untuk mobil ini (mis. ground station
  // unit lain yang salah kunci).
  uint32_t foreignCount() const { return _foreignCount; }

 private:
  void connectWifi();
  void serviceWifi();
  void receivePackets();
  void handleControl(const ControlPacket& packet);
  void sendTelemetry(uint16_t seqEcho);
  void sampleBattery();
  bool acceptSequence(uint16_t seq);

  WiFiUDP _udp;
  IPAddress _peerIp;
  uint16_t _peerPort = 0;
  bool _hasPeer = false;

  bool _wifiConnected = false;
  uint32_t _lastWifiAttemptMs = 0;

  int16_t _steer = 0;
  int16_t _throttle = 0;
  uint8_t _brake = 0;

  bool _armed = false;
  bool _failsafe = true;
  bool _prevArmedFlag = false;
  bool _servoCalibration = false;
  int16_t _servoSteer = 0;

  uint16_t _lastSeq = 0;
  bool _hasSeq = false;
  uint32_t _lastValidMs = 0;

  uint16_t _vbatMv = 0;
  uint32_t _lastBatteryMs = 0;

  uint32_t _rxCount = 0;
  uint32_t _badCount = 0;
  uint32_t _staleCount = 0;
  uint32_t _foreignCount = 0;

  uint8_t _buffer[64];
};
