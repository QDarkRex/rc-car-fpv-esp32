// console.h — konsol diagnostik lewat Serial Monitor, di dalam firmware asli.
//
// Gunanya: kalau stir atau pedal tidak bekerja, Anda bisa langsung menguji
// motor dan servo dari Serial Monitor TANPA flash sketch lain. Itu memisahkan
// tiga kemungkinan yang gejalanya mirip:
//
//   1. Ground station tidak mengirim  -> "status" menunjukkan rx tidak naik
//   2. Firmware menerima tapi tidak menggerakkan -> nilai steer/throttle
//      terisi, tapi duty_ena tetap 0
//   3. Firmware menggerakkan tapi hardware diam -> duty_ena terisi penuh,
//      motor tetap tidak berputar
//
// KEAMANAN: mode uji hanya bisa dinyalakan saat mobil TIDAK armed, dan
// selama mode uji aktif perintah dari ground station diabaikan sepenuhnya.
// Motor juga berhenti sendiri kalau tidak ada perintah baru selama beberapa
// detik, supaya tidak ada motor yang berputar terus karena Anda lupa.

#pragma once

#include <Arduino.h>

#include "config.h"
#include "drive.h"
#include "link.h"

class Console {
 public:
  void begin(Drive* drive, CarLink* link);

  // Panggil tiap loop, SEBELUM drive.update(). Membaca Serial, menjalankan
  // perintah, dan menyetel perintah Drive saat mode uji aktif.
  void update();

  // Panggil tiap loop, SESUDAH drive.update(). Perintah "servo <us>" menulis
  // lebar pulsa mentah, tapi drive.update() menghitung ulang servo dari
  // _targetSteer setiap siklus dan akan menimpanya. Override diterapkan lagi
  // di sini supaya nilainya bertahan sampai Anda mengetik "steer" atau "stop".
  void postDrive();

  // Selama true, loop() utama harus MENGABAIKAN perintah dari ground station
  // dan membiarkan konsol yang mengendalikan Drive.
  bool testMode() const { return _testMode; }

 private:
  void handleLine(String line);
  void printHelp() const;
  void printStatus() const;
  void printVbat() const;
  bool requireTestMode() const;
  void enterTestMode();
  void exitTestMode();

  Drive* _drive = nullptr;
  CarLink* _link = nullptr;

  bool _testMode = false;
  int16_t _steer = 0;
  int16_t _throttle = 0;
  uint8_t _brake = 0;
  uint16_t _servoOverrideUs = 0;   // 0 = tidak ada override
  uint32_t _lastCommandMs = 0;
  String _buffer;
};
