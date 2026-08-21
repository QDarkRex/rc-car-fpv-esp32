#include "console.h"

#include <WiFi.h>

#include "protocol.h"

// Motor berhenti sendiri kalau tidak ada perintah baru selama ini, supaya
// tidak ada motor berputar terus karena operator lupa mengetik "stop".
#define CONSOLE_AUTOSTOP_MS 3000

void Console::begin(Drive* drive, CarLink* link) {
  _drive = drive;
  _link = link;
  _lastCommandMs = millis();
  Serial.println("[KONSOL] ketik \"help\" untuk daftar perintah diagnostik");
}

void Console::update() {
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '\n') {
      handleLine(_buffer);
      _buffer = "";
    } else if (c != '\r') {
      if (_buffer.length() < 64) {
        _buffer += c;
      }
    }
  }

  if (!_testMode) {
    return;
  }

  // Pengaman mode uji: hentikan motor kalau sudah lama tidak ada perintah.
  const bool moving = (_throttle != 0) || (_brake != 0);
  if (moving && (millis() - _lastCommandMs) > CONSOLE_AUTOSTOP_MS) {
    _throttle = 0;
    _brake = 0;
    Serial.println("[KONSOL] auto-stop: tidak ada perintah 3 detik");
  }

  _drive->setCommand(_steer, _throttle, _brake);
}

void Console::postDrive() {
  if (_testMode && _servoOverrideUs != 0) {
    _drive->testServoMicros(_servoOverrideUs);
  }
}

bool Console::requireTestMode() const {
  if (_testMode) {
    return true;
  }
  Serial.println("[KONSOL] mode uji belum aktif. Ketik \"test on\" dulu.");
  return false;
}

void Console::enterTestMode() {
  if (_link->armed()) {
    Serial.println("[KONSOL] DITOLAK: mobil sedang ARMED dari ground station.");
    Serial.println("[KONSOL] Disarm dulu (tekan SPASI di main.py), baru coba lagi.");
    return;
  }

  _testMode = true;
  _steer = 0;
  _throttle = 0;
  _brake = 0;
  _servoOverrideUs = 0;
  _lastCommandMs = millis();
  _drive->neutral();

  Serial.println();
  Serial.println("=== MODE UJI AKTIF ===");
  Serial.println("Perintah dari ground station DIABAIKAN selama mode ini.");
  Serial.println("Motor berhenti sendiri kalau 3 detik tanpa perintah baru.");
  Serial.println("Ketik \"test off\" untuk kembali normal.");
  Serial.println();
}

void Console::exitTestMode() {
  _testMode = false;
  _steer = 0;
  _throttle = 0;
  _brake = 0;
  _servoOverrideUs = 0;
  _drive->neutral();
  Serial.println("[KONSOL] mode uji MATI - kendali kembali ke ground station");
}

void Console::printHelp() const {
  Serial.println();
  Serial.println("=== Perintah konsol RC Car ===");
  Serial.println("  status                selalu bisa - keadaan lengkap saat ini");
  Serial.println("  vbat                  selalu bisa - pembacaan ADC baterai");
  Serial.println("  test on | test off    nyalakan/matikan mode uji");
  Serial.println();
  Serial.println("  Perintah berikut HANYA jalan saat mode uji aktif:");
  Serial.println("  steer <-1000..1000>   belok. negatif=kiri, positif=kanan");
  Serial.println("  motor <-1000..1000>   gas. negatif=mundur, positif=maju");
  Serial.println("  brake <0..255>        rem");
  Serial.println("  servo <us>            tulis lebar pulsa servo LANGSUNG,");
  Serial.println("                        untuk mencari SERVO_MIN_US/MAX_US");
  Serial.println("  stop                  netralkan semua");
  Serial.println();
}

void Console::printStatus() const {
  const char* state = _testMode          ? "MODE UJI"
                      : _link->failsafe() ? "FAILSAFE"
                      : _link->armed()    ? "ARMED"
                                          : "DISARMED";

  Serial.println();
  Serial.println("=== STATUS ===");
  Serial.printf("  keadaan       : %s\n", state);
  Serial.printf("  WiFi          : %s", _link->wifiConnected() ? "tersambung" : "TERPUTUS");
  if (_link->wifiConnected()) {
    Serial.print(" IP ");
    Serial.print(WiFi.localIP());
    Serial.printf(" rssi %d dBm", WiFi.RSSI());
  }
  Serial.println();

  Serial.printf("  paket masuk   : rx %lu  rusak %lu  basi %lu\n",
                (unsigned long)_link->rxCount(),
                (unsigned long)_link->badCount(),
                (unsigned long)_link->staleCount());

  Serial.println("  -- perintah dari ground station --");
  Serial.printf("    steer %+5d | throttle %+5d | brake %3u\n",
                _link->steer(), _link->throttle(), _link->brake());

  if (_testMode) {
    Serial.println("  -- perintah dari konsol (yang sedang dipakai) --");
    Serial.printf("    steer %+5d | throttle %+5d | brake %3u\n",
                  _steer, _throttle, _brake);
  }

  Serial.println("  -- keluaran ke hardware --");
  Serial.printf("    servo %4u us | duty_ena %4lu / %d | arah %+d\n",
                _drive->servoMicros(), (unsigned long)_drive->motorDuty(),
                MOTOR_PWM_MAX, _drive->direction());
  Serial.printf("    throttle setelah slew: %+5d\n", _drive->appliedThrottle());

  Serial.printf("  baterai       : %.2f V\n", _link->vbatMv() / 1000.0f);
  Serial.println("  -- pin --");
  Serial.printf("    ENA %d  IN1 %d  IN2 %d  SERVO %d  VBAT %d\n",
                PIN_ENA, PIN_IN1, PIN_IN2, PIN_SERVO, PIN_VBAT);
  Serial.printf("    servo: min %d  tengah %d  maks %d  invert %d\n",
                SERVO_MIN_US, SERVO_CENTER_US, SERVO_MAX_US, SERVO_INVERT);
  Serial.printf("    motor: deadband %d  min_duty %d  invert %d\n",
                MOTOR_DEADBAND, MOTOR_MIN_DUTY, MOTOR_INVERT);
  Serial.println();
}

void Console::printVbat() const {
  uint32_t sum = 0;
  for (int i = 0; i < VBAT_SAMPLES; i++) {
    sum += analogReadMilliVolts(PIN_VBAT);
  }
  const uint32_t pinMv = sum / VBAT_SAMPLES;
  Serial.printf("[VBAT] pin GPIO%d = %lu mV mentah -> %.2f V setelah rasio %.3f\n",
                PIN_VBAT, (unsigned long)pinMv,
                pinMv * VBAT_DIVIDER_RATIO / 1000.0f, VBAT_DIVIDER_RATIO);
}

void Console::handleLine(String line) {
  line.trim();
  if (line.length() == 0) {
    return;
  }

  const int space = line.indexOf(' ');
  String cmd = (space < 0) ? line : line.substring(0, space);
  String arg = (space < 0) ? "" : line.substring(space + 1);
  arg.trim();
  cmd.toLowerCase();
  arg.toLowerCase();

  _lastCommandMs = millis();

  if (cmd == "help") {
    printHelp();

  } else if (cmd == "status") {
    printStatus();

  } else if (cmd == "vbat") {
    printVbat();

  } else if (cmd == "test") {
    if (arg == "on") {
      enterTestMode();
    } else if (arg == "off") {
      exitTestMode();
    } else {
      Serial.println("[KONSOL] pakai \"test on\" atau \"test off\"");
    }

  } else if (cmd == "steer") {
    if (!requireTestMode()) return;
    _steer = (int16_t)constrain(arg.toInt(), -RC_AXIS_MAX, RC_AXIS_MAX);
    _servoOverrideUs = 0;   // kembali ke pemetaan steer normal
    Serial.printf("[OK] steer -> %+d\n", _steer);

  } else if (cmd == "motor") {
    if (!requireTestMode()) return;
    _throttle = (int16_t)constrain(arg.toInt(), -RC_AXIS_MAX, RC_AXIS_MAX);
    _brake = 0;
    Serial.printf("[OK] motor -> %+d\n", _throttle);

  } else if (cmd == "brake") {
    if (!requireTestMode()) return;
    _brake = (uint8_t)constrain(arg.toInt(), 0, 255);
    Serial.printf("[OK] brake -> %u\n", _brake);

  } else if (cmd == "servo") {
    if (!requireTestMode()) return;
    if (arg.length() == 0) {
      Serial.println("[KONSOL] contoh: servo 1350");
      return;
    }
    // Ditulis setelah setCommand() di update() supaya nilai ini yang menang
    // untuk satu siklus -- lihat catatan di loop() rc_car_esp32.ino.
    _servoOverrideUs = (uint16_t)arg.toInt();
    _drive->testServoMicros(_servoOverrideUs);
    Serial.printf("[OK] servo -> %u us (dijepit ke batas %d..%d)\n",
                  _drive->servoMicros(), SERVO_MIN_US, SERVO_MAX_US);

  } else if (cmd == "stop") {
    _steer = 0;
    _throttle = 0;
    _brake = 0;
    _servoOverrideUs = 0;
    if (_testMode) {
      _drive->neutral();
    }
    Serial.println("[OK] netral");

  } else {
    Serial.printf("[KONSOL] perintah tidak dikenal: \"%s\" - ketik \"help\"\n",
                  cmd.c_str());
  }
}
