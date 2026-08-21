/*
 * rc_car_esp32 — otak mobil RC.
 *
 * Menerima perintah UDP dari ground station, menggerakkan motor belakang
 * lewat L298N (OUT1/OUT2) dan servo kemudi digital.
 *
 * Board di Arduino IDE : "ESP32 Dev Module"
 * ESP32 core           : 3.x  (memakai API ledcAttach gaya baru)
 * Kecepatan Serial     : 115200
 *
 * SEBELUM FLASH PERTAMA KALI, buka config.h dan isi:
 *   - WIFI_SSID dan WIFI_PASS
 *   - VBAT_DIVIDER_RATIO sesuai resistor yang benar-benar Anda pasang
 *
 * Pemetaan pin dan skema daya lengkap ada di docs/wiring.md
 *
 * Perhatian daya: JANGAN mengambil 5V dari pin 5V L298N untuk servo dan
 * kedua ESP32. Regulator linear di board itu hanya sanggup ~0,5 A sedangkan
 * servo saja bisa menarik 1,5-2,5 A saat menahan. Pakai step-down terpisah.
 */

#include <WiFi.h>

#include "config.h"
#include "console.h"
#include "drive.h"
#include "link.h"
#include "protocol.h"

Drive drive;
Console console;
CarLink carLink;   // JANGAN diberi nama "link": bentrok dengan fungsi POSIX link() dari unistd.h

static uint32_t lastStatusMs = 0;
static uint32_t lastLedMs = 0;
static bool ledState = false;

// LED onboard sebagai indikator status yang bisa dibaca tanpa laptop:
//   nyala terus        -> ARMED, motor bisa bergerak
//   kedip lambat 1 Hz  -> tersambung, disarmed, aman didekati
//   kedip cepat 5 Hz   -> WiFi belum tersambung
//   kedip ganda        -> failsafe, tautan putus
static void updateStatusLed() {
  const uint32_t now = millis();

  if (carLink.armed()) {
    digitalWrite(PIN_LED, HIGH);
    return;
  }

  uint32_t interval;
  if (!carLink.wifiConnected()) {
    interval = 100;                       // kedip cepat
  } else if (carLink.failsafe()) {
    interval = ((now % 1000) < 300) ? 80 : 400;   // kedip ganda
  } else {
    interval = 500;                       // kedip lambat
  }

  if (now - lastLedMs >= interval) {
    lastLedMs = now;
    ledState = !ledState;
    digitalWrite(PIN_LED, ledState ? HIGH : LOW);
  }
}

static void printStatus() {
#if SERIAL_STATUS_MS > 0
  const uint32_t now = millis();
  if (now - lastStatusMs < SERIAL_STATUS_MS) {
    return;
  }
  lastStatusMs = now;

  // Saat mode uji, nilai dari carLink selalu nol dan akan menyesatkan.
  // Tampilkan keluaran Drive yang sesungguhnya -- itu yang sedang diuji.
  if (console.testMode()) {
    Serial.printf("MODE UJI | servo %4u us | duty_ena %4lu/%d | arah %+d | "
                  "gas setelah slew %+5d\n",
                  drive.servoMicros(), (unsigned long)drive.motorDuty(),
                  MOTOR_PWM_MAX, drive.direction(), drive.appliedThrottle());
    return;
  }

  const char* state = carLink.failsafe() ? "FAILSAFE"
                    : carLink.armed()    ? "ARMED   "
                                      : "DISARMED";

  Serial.printf(
      "%s | stir %+5d (%4u us) | gas %+5d -> %+5d | rem %3u | %5.2fV | rssi %4d "
      "| rx %lu bad %lu basi %lu\n",
      state, carLink.steer(), drive.servoMicros(), carLink.throttle(),
      drive.appliedThrottle(), carLink.brake(), carLink.vbatMv() / 1000.0f,
      carLink.wifiConnected() ? WiFi.RSSI() : 0,
      (unsigned long)carLink.rxCount(), (unsigned long)carLink.badCount(),
      (unsigned long)carLink.staleCount());
#endif
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  Serial.println();
  Serial.println("=== RC Car ESP32 ===");

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  // Drive disiapkan LEBIH DULU daripada WiFi, supaya pin motor sudah berada
  // di keadaan netral yang pasti sebelum ada waktu tunggu koneksi apa pun.
  // Pin ESP32 mengambang saat boot, dan pin ENA yang mengambang bisa membuat
  // motor tersentak sebelum program sempat berjalan.
  drive.begin();
  Serial.println("[BOOT] motor netral, servo di tengah");

  carLink.begin();
  console.begin(&drive, &carLink);
  Serial.println("[BOOT] siap - menunggu paket kontrol");
}

void loop() {
  carLink.update();

  // Konsol dibaca lebih dulu supaya "test on" langsung berlaku di siklus ini.
  console.update();

  if (console.testMode()) {
    // Mode uji: perintah dari ground station DIABAIKAN sepenuhnya. Console
    // sudah memanggil drive.setCommand() sendiri di console.update().
  } else if (carLink.failsafe() || !carLink.armed()) {
    // Netral bukan hanya "throttle nol": servo juga dikembalikan ke tengah
    // dan keadaan slew internal dinolkan, supaya arming berikutnya selalu
    // dimulai dari kondisi yang sama dan bisa diprediksi.
    drive.neutral();
  } else {
    drive.setCommand(carLink.steer(), carLink.throttle(), carLink.brake());
  }

  drive.update();

  // SESUDAH drive.update(): perintah "servo <us>" menulis lebar pulsa mentah,
  // dan drive.update() menghitung ulang servo tiap siklus. Tanpa dipanggil di
  // sini, override itu akan tertimpa sebelum sempat terlihat.
  console.postDrive();

  updateStatusLed();
  printStatus();
}
