/*
 * rc_car_diag — sketch diagnostik untuk menguji motor dan servo LANGSUNG
 * lewat Serial Monitor, tanpa WiFi/UDP/kalibrasi stir sama sekali.
 *
 * Gunanya: memisahkan masalah hardware (wiring, jumper, daya) dari masalah
 * software (protokol, jaringan, kalibrasi PXN). Kalau lewat sketch ini motor
 * dan servo tetap tidak bergerak, masalahnya pasti fisik -- bukan kode.
 *
 * SKETCH INI SEMENTARA. Flash rc_car_esp32 (firmware asli) lagi setelah
 * selesai uji coba.
 *
 * Board  : ESP32 Dev Module
 * Serial : 115200, line ending "Newline" atau "Both NL & CR"
 *
 * Perintah (ketik lalu Enter):
 *   motor <-1000..1000>   jalankan motor. Positif=maju, negatif=mundur, 0=coast.
 *                         Ini nilai MENTAH -- tidak ada deadband/slew seperti
 *                         firmware asli, supaya Anda bisa merasakan persis di
 *                         angka berapa motor MULAI berputar.
 *   servo <us>            set servo ke microseconds RAW (600-2400), untuk
 *                         mencari batas mekanis aman sebelum ditulis ke
 *                         SERVO_MIN_US/SERVO_MAX_US di config.h.
 *   brake <0..255>        uji pengereman L298N (IN1=IN2=HIGH, duty=n).
 *   stop                  motor coast, servo tengah (1500us), brake 0.
 *   vbat                  cetak pembacaan ADC mentah di GPIO34 (untuk
 *                         mengecek pembagi tegangan terpisah dari masalah ini).
 *   help                  tampilkan daftar perintah ini lagi.
 *
 * Keamanan: kalau tidak ada perintah baru selama 3 detik SEMENTARA motor
 * masih menyala, motor otomatis di-coast. Servo tetap menahan posisi
 * terakhir (menahan posisi bukan bahaya, coasting terus-menerus juga aman
 * karena roda di udara).
 */

#include <Arduino.h>

// Pin -- HARUS SAMA dengan firmware/rc_car_esp32/config.h saat ini.
#define PIN_ENA 4
#define PIN_IN1 15
#define PIN_IN2 22
#define PIN_SERVO 13
#define PIN_VBAT 34
#define PIN_LED 2

#define MOTOR_PWM_FREQ_HZ 16000
#define MOTOR_PWM_BITS 10
#define MOTOR_PWM_MAX ((1 << MOTOR_PWM_BITS) - 1)  // 1023

#define SERVO_FREQ_HZ 50
#define SERVO_PWM_BITS 16
#define SERVO_RAW_MIN_US 600   // batas mentah lebar untuk EKSPLORASI, bukan
#define SERVO_RAW_MAX_US 2400  // batas produksi. Dengarkan servo mendengung
                                // di ujung -- itu tandanya sudah kelewatan.

#define AUTO_STOP_MS 3000

static int16_t motorValue = 0;   // -1000..1000, nilai mentah tanpa deadband
static int8_t motorDir = 0;      // -1, 0, +1
static uint16_t servoUs = 1500;
static uint8_t servoPin = PIN_SERVO;  // bisa diganti saat jalan lewat "servopin"
static uint8_t brakeValue = 0;
static bool braking = false;
static uint32_t lastCommandMs = 0;

// ------------------------------------------------------------- kendali fisik

static void writeServo(uint16_t us) {
  us = constrain(us, (uint16_t)SERVO_RAW_MIN_US, (uint16_t)SERVO_RAW_MAX_US);
  const uint32_t maxDuty = (1UL << SERVO_PWM_BITS) - 1UL;
  const uint32_t periodUs = 1000000UL / SERVO_FREQ_HZ;
  const uint32_t duty = (uint32_t)(((uint64_t)us * maxDuty) / periodUs);
  ledcWrite(servoPin, duty);
  servoUs = us;
}

// Pindahkan sinyal servo ke GPIO lain tanpa flash ulang. Berguna untuk
// membuktikan apakah masalahnya di pin tertentu atau di servo/kabelnya.
static bool attachServo(uint8_t pin) {
  ledcDetach(servoPin);
  if (!ledcAttach(pin, SERVO_FREQ_HZ, SERVO_PWM_BITS)) {
    Serial.printf("[ERR] ledcAttach GAGAL di GPIO %u -- pin dipakai fungsi "
                  "lain, atau input-only (34-39)\n", pin);
    // Coba pulihkan ke pin sebelumnya supaya tidak kehilangan kendali.
    ledcAttach(servoPin, SERVO_FREQ_HZ, SERVO_PWM_BITS);
    writeServo(servoUs);
    return false;
  }
  servoPin = pin;
  writeServo(servoUs);
  return true;
}

static void coastMotor() {
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  ledcWrite(PIN_ENA, 0);
  motorValue = 0;
  motorDir = 0;
  braking = false;
}

static void writeMotor(int16_t value) {
  value = constrain(value, -1000, 1000);
  motorValue = value;
  braking = false;

  if (value == 0) {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, LOW);
    ledcWrite(PIN_ENA, 0);
    motorDir = 0;
    return;
  }

  if (value > 0) {
    digitalWrite(PIN_IN1, HIGH);
    digitalWrite(PIN_IN2, LOW);
    motorDir = 1;
  } else {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, HIGH);
    motorDir = -1;
  }

  // Pemetaan LINEAR langsung dari -1000..1000 ke 0..1023, TANPA deadband
  // atau MOTOR_MIN_DUTY seperti firmware produksi. Ini sengaja, supaya
  // Anda melihat hubungan mentah antara angka yang diketik dan duty PWM
  // sesungguhnya -- berguna untuk menentukan MOTOR_DEADBAND/MOTOR_MIN_DUTY
  // yang tepat di config.h nanti.
  const uint32_t duty = ((uint32_t)abs(value) * MOTOR_PWM_MAX) / 1000;
  ledcWrite(PIN_ENA, duty);
}

static void writeBrake(uint8_t value) {
  brakeValue = value;
  motorValue = 0;
  motorDir = 0;
  braking = value > 0;

  digitalWrite(PIN_IN1, HIGH);
  digitalWrite(PIN_IN2, HIGH);
  const uint32_t duty = ((uint32_t)value * MOTOR_PWM_MAX) / 255;
  ledcWrite(PIN_ENA, duty);
}

// ------------------------------------------------------------- perintah

static void printHelp() {
  Serial.println();
  Serial.println("=== Perintah rc_car_diag ===");
  Serial.println("  motor <-1000..1000>   jalankan motor mentah (+maju/-mundur/0=coast)");
  Serial.println("  servo <us>            set servo ke microseconds mentah (600-2400)");
  Serial.println("  servopin <gpio>       pindahkan sinyal servo ke GPIO lain (uji 13 vs 33)");
  Serial.println("  brake <0..255>        uji pengereman (IN1=IN2=HIGH)");
  Serial.println("  stop                  motor coast, servo tengah, brake 0");
  Serial.println("  vbat                  cetak ADC mentah GPIO34");
  Serial.println("  help                  tampilkan ini lagi");
  Serial.println();
}

static void printStatus() {
  Serial.printf(
      "[STATUS] motor=%+5d arah=%+d duty_ena=%4u | servo=%4u us (GPIO %u) | "
      "rem=%3u aktif=%s\n",
      motorValue, motorDir, ledcRead(PIN_ENA), servoUs, servoPin, brakeValue,
      braking ? "ya" : "tidak");
}

static void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  int space = line.indexOf(' ');
  String cmd = (space < 0) ? line : line.substring(0, space);
  String argStr = (space < 0) ? "" : line.substring(space + 1);
  argStr.trim();
  cmd.toLowerCase();

  lastCommandMs = millis();

  if (cmd == "motor") {
    if (argStr.length() == 0) {
      Serial.println("[ERR] contoh: motor 500");
      return;
    }
    writeMotor((int16_t)argStr.toInt());
    Serial.printf("[OK] motor -> %d\n", motorValue);

  } else if (cmd == "servo") {
    if (argStr.length() == 0) {
      Serial.println("[ERR] contoh: servo 1500");
      return;
    }
    writeServo((uint16_t)argStr.toInt());
    Serial.printf("[OK] servo -> %u us\n", servoUs);

  } else if (cmd == "brake") {
    if (argStr.length() == 0) {
      Serial.println("[ERR] contoh: brake 200");
      return;
    }
    writeBrake((uint8_t)constrain(argStr.toInt(), 0, 255));
    Serial.printf("[OK] brake -> %u\n", brakeValue);

  } else if (cmd == "servopin") {
    if (argStr.length() == 0) {
      Serial.printf("[INFO] pin servo sekarang: GPIO %u. Contoh: servopin 33\n",
                    servoPin);
      return;
    }
    const uint8_t pin = (uint8_t)argStr.toInt();
    if (attachServo(pin)) {
      Serial.printf("[OK] sinyal servo pindah ke GPIO %u (posisi %u us "
                    "dipertahankan)\n", servoPin, servoUs);
      Serial.println("     Jangan lupa pindahkan kabelnya juga.");
    }

  } else if (cmd == "stop") {
    coastMotor();
    writeServo(1500);
    Serial.println("[OK] motor coast, servo tengah");

  } else if (cmd == "vbat") {
    uint32_t sum = 0;
    for (int i = 0; i < 16; i++) sum += analogReadMilliVolts(PIN_VBAT);
    Serial.printf("[VBAT] rata-rata pin GPIO34 = %lu mV (mentah, BELUM dikali "
                  "rasio pembagi tegangan)\n", (unsigned long)(sum / 16));

  } else if (cmd == "help") {
    printHelp();

  } else {
    Serial.printf("[ERR] perintah tidak dikenal: \"%s\" -- ketik \"help\"\n",
                  cmd.c_str());
  }
}

// ------------------------------------------------------------- setup/loop

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  digitalWrite(PIN_LED, HIGH);  // LED menyala terus = sketch diagnostik aktif

  if (!ledcAttach(PIN_ENA, MOTOR_PWM_FREQ_HZ, MOTOR_PWM_BITS)) {
    Serial.println("[BOOT] GAGAL menyiapkan PWM motor (ledcAttach ENA) -- "
                    "cek apakah GPIO4 dipakai fungsi lain");
  }
  if (!ledcAttach(servoPin, SERVO_FREQ_HZ, SERVO_PWM_BITS)) {
    Serial.printf("[BOOT] GAGAL menyiapkan PWM servo di GPIO %u\n", servoPin);
  }

  ledcWrite(PIN_ENA, 0);
  writeServo(1500);

  Serial.println();
  Serial.println("=== rc_car_diag siap ===");
  Serial.println("Sketch ini TIDAK memakai WiFi. Uji motor/servo langsung.");
  printHelp();
  lastCommandMs = millis();
}

void loop() {
  static String buffer;

  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleLine(buffer);
      buffer = "";
    } else if (c != '\r') {
      buffer += c;
    }
  }

  // Pengaman: motor tidak boleh terus menyala tanpa perintah baru.
  if (motorValue != 0 && (millis() - lastCommandMs) > AUTO_STOP_MS) {
    coastMotor();
    Serial.println("[AUTO-STOP] tidak ada perintah 3 detik -- motor dihentikan");
  }

  static uint32_t lastPrint = 0;
  if (millis() - lastPrint >= 1000) {
    lastPrint = millis();
    printStatus();
  }
}
