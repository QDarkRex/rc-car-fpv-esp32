// drive.h — kendali motor (L298N) dan servo kemudi.
//
// Kelas ini tidak tahu apa-apa soal jaringan. Ia hanya menerima perintah
// dalam skala -1000..1000 dan menerjemahkannya menjadi sinyal pin, sambil
// menegakkan batas keselamatan hardware: deadband, slew rate, jeda balik
// arah, dan batas mekanis servo.

#pragma once

#include <Arduino.h>
#include <stdint.h>

#include "config.h"

class Drive {
 public:
  void begin();

  // Perintah dari sisi darat.
  // steer   : -1000..1000, negatif = kiri
  // throttle: -1000..1000, negatif = mundur
  // brake   : 0..255, 0 = tidak mengerem. Kalau di atas ambang, rem menang
  //           atas throttle -- lihat update() di drive.cpp.
  void setCommand(int16_t steer, int16_t throttle, uint8_t brake);

  // Netralkan segera: motor berhenti, servo ke tengah.
  // Dipanggil saat failsafe, disarm, dan saat boot.
  void neutral();

  // Panggil sesering mungkin dari loop(). Di sinilah slew rate, deadband,
  // dan jeda balik arah benar-benar diterapkan.
  void update();

  int16_t appliedThrottle() const { return _appliedThrottle; }
  uint16_t servoMicros() const { return _servoUs; }
  int8_t direction() const { return _direction; }

  // Duty PWM yang benar-benar sedang keluar di pin ENA. Dipakai konsol
  // serial untuk membedakan "ESP32 tidak mengirim apa-apa" dari "ESP32
  // mengirim penuh tapi motor tetap diam" -- dua masalah yang sangat
  // berbeda penyebabnya.
  uint32_t motorDuty() const;

  // KHUSUS DIAGNOSTIK. Menulis lebar pulsa servo langsung, melewati seluruh
  // pemetaan steer, untuk mencari SERVO_MIN_US/SERVO_MAX_US secara empiris.
  // Batas mekanis di writeServoMicros() TETAP berlaku, jadi ini tidak bisa
  // dipakai untuk menabrakkan servo ke ujung linkage.
  void testServoMicros(uint16_t micros) { writeServoMicros(micros); }

 private:
  void applyMotorOutput(int8_t wantDirection, uint32_t magnitude);
  // originalDirection: arah mobil TEPAT SEBELUM rem diinjak (-1/0/+1). Duty
  // dipetakan dari besaran brake seperti biasa, tapi IN1/IN2 diarahkan ke
  // LAWAN dari originalDirection -- ini bagian "reverse pulse" (plugging).
  // Lihat update() dan BRAKE_REVERSE_PULSE_MS di config.h untuk mekanisme
  // dan batas waktu pulsa ini.
  void applyBrakeOutput(uint8_t brake, int8_t originalDirection);
  void writeServoMicros(uint16_t micros);
  void coast();

  int16_t _targetThrottle = 0;
  int16_t _appliedThrottle = 0;
  int16_t _targetSteer = 0;
  uint8_t _targetBrake = 0;
  uint16_t _servoUs = SERVO_CENTER_US;
  int8_t _direction = 0;              // -1 mundur, 0 diam, +1 maju
  bool _braking = false;
  uint32_t _lastUpdateMs = 0;
  uint32_t _reverseGuardUntilMs = 0;

  // Arah mobil TEPAT SEBELUM rem diinjak (-1/0/+1). Dipakai untuk menentukan
  // arah pulsa dorong-balik (reverse pulse) saat mengerem -- kalau mobil
  // sudah diam (0) saat rem diinjak, tidak pernah ada pulsa mundur sama
  // sekali, cukup coast. Lihat update() di drive.cpp.
  int8_t _brakeDirection = 0;
  // Kapan pulsa dorong-balik mulai dihitung (millis()). 0 berarti belum
  // mulai -- baru diisi begitu REVERSE_GUARD_MS di awal rem selesai.
  uint32_t _brakePulseStartMs = 0;
};
