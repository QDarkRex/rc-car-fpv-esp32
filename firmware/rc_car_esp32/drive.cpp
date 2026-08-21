#include "drive.h"

#include "protocol.h"

void Drive::begin() {
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);

  // API LEDC gaya core 3.x. Tutorial lama memakai ledcSetup() +
  // ledcAttachPin() yang sudah tidak ada di ESP32 core 3.x.
  if (!ledcAttach(PIN_ENA, MOTOR_PWM_FREQ_HZ, MOTOR_PWM_BITS)) {
    Serial.println("[DRIVE] GAGAL menyiapkan PWM motor");
  }
  ledcWrite(PIN_ENA, 0);

  if (!ledcAttach(PIN_SERVO, SERVO_FREQ_HZ, SERVO_PWM_BITS)) {
    Serial.println("[DRIVE] GAGAL menyiapkan PWM servo");
  }

  _lastUpdateMs = millis();
  neutral();
}

void Drive::setCommand(int16_t steer, int16_t throttle, uint8_t brake) {
  _targetSteer = constrain(steer, -RC_AXIS_MAX, RC_AXIS_MAX);
  _targetThrottle = constrain(throttle, -RC_AXIS_MAX, RC_AXIS_MAX);
  _targetBrake = brake;
}

void Drive::neutral() {
  _targetThrottle = 0;
  _appliedThrottle = 0;
  _targetSteer = 0;
  _targetBrake = 0;
  _direction = 0;
  _braking = false;
  coast();
  writeServoMicros(SERVO_CENTER_US);
}

void Drive::coast() {
  // IN1=IN2=LOW membuat motor berputar bebas (coast), bukan mengerem.
  // Mengerem (IN1=IN2=HIGH) pada mobil yang sedang melaju akan menghentak
  // gearbox dan menarik arus besar, jadi bukan pilihan yang aman untuk
  // dipakai otomatis saat failsafe.
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  ledcWrite(PIN_ENA, 0);
}

void Drive::update() {
  const uint32_t now = millis();
  const uint32_t dt = now - _lastUpdateMs;
  if (dt == 0) {
    return;
  }
  _lastUpdateMs = now;

  // --- servo: langsung, tanpa slew. Servo punya peredamnya sendiri.
  //
  // SERVO_INVERT membalik arah belok tanpa perlu menukar SERVO_MIN_US dengan
  // SERVO_MAX_US -- keduanya harus tetap MIN < MAX supaya constrain() di
  // writeServoMicros() bekerja benar sebagai pengaman batas mekanis.
#if SERVO_INVERT
  const int32_t steerCmd = -(int32_t)_targetSteer;
#else
  const int32_t steerCmd = (int32_t)_targetSteer;
#endif

  int32_t micros;
  if (steerCmd >= 0) {
    micros = SERVO_CENTER_US +
             steerCmd * (SERVO_MAX_US - SERVO_CENTER_US) / RC_AXIS_MAX;
  } else {
    // Dihitung terpisah agar endpoint kiri dan kanan boleh tidak simetris,
    // yang lazim terjadi pada linkage kemudi sungguhan.
    micros = SERVO_CENTER_US +
             steerCmd * (SERVO_CENTER_US - SERVO_MIN_US) / RC_AXIS_MAX;
  }
  writeServoMicros((uint16_t)micros);

  // --- motor: slew rate. Menuju target normal, atau menuju nol kalau
  // sedang mengerem -- supaya keluar dari rem tidak menyentak throttle.
  const bool wantBrake = _targetBrake > BRAKE_DEADBAND;
  const int16_t throttleGoal = wantBrake ? 0 : _targetThrottle;

  int32_t maxDelta = ((int32_t)MOTOR_SLEW_PER_SEC * (int32_t)dt) / 1000;
  if (maxDelta < 1) {
    maxDelta = 1;
  }
  int32_t delta = (int32_t)throttleGoal - (int32_t)_appliedThrottle;
  delta = constrain(delta, -maxDelta, maxDelta);
  _appliedThrottle = (int16_t)((int32_t)_appliedThrottle + delta);

  // --- prioritas 1: rem. Menang atas throttle setiap kali brake di atas
  // ambang -- lihat docs/protocol.md soal kenapa rem punya field sendiri.
  if (wantBrake) {
    if (now < _reverseGuardUntilMs) {
      coast();
      return;
    }
    if (!_braking && _direction != 0) {
      // Sedang bergerak lalu rem diinjak: matikan H-bridge dulu dan beri
      // jeda balik arah sebelum IN1/IN2 sama-sama HIGH. Tanpa jeda ini,
      // transisi dari satu sisi HIGH langsung ke dua-duanya HIGH berisiko
      // shoot-through yang sama seperti berbalik arah biasa.
      coast();
      _direction = 0;
      _reverseGuardUntilMs = now + REVERSE_GUARD_MS;
      return;
    }
    applyBrakeOutput(_targetBrake);
    _braking = true;
    return;
  }

  // --- keluar dari mode rem menuju gerak: jeda balik arah berlaku lagi di
  // sini juga, dengan alasan sama seperti di atas tapi arah terbalik.
  if (_braking) {
    coast();
    _braking = false;
    _direction = 0;
    _reverseGuardUntilMs = now + REVERSE_GUARD_MS;
    return;
  }

  // --- arah yang diinginkan, setelah deadband
  int8_t want = 0;
  if (_appliedThrottle > MOTOR_DEADBAND) {
    want = 1;
  } else if (_appliedThrottle < -MOTOR_DEADBAND) {
    want = -1;
  }

  // --- jeda balik arah (anti shoot-through)
  if (now < _reverseGuardUntilMs) {
    coast();
    return;
  }
  if (want != 0 && _direction != 0 && want != _direction) {
    // Matikan kedua sisi jembatan sepenuhnya sebelum arah baru diterapkan.
    // Tanpa jeda ini, kedua sisi H-bridge bisa sesaat menyala bersamaan dan
    // menghubung-singkat catu motor lewat L298N.
    coast();
    _direction = 0;
    _appliedThrottle = 0;
    _reverseGuardUntilMs = now + REVERSE_GUARD_MS;
    return;
  }

  applyMotorOutput(want, (uint32_t)abs(_appliedThrottle));
}

void Drive::applyMotorOutput(int8_t wantDirection, uint32_t magnitude) {
  if (wantDirection == 0) {
    coast();
    _direction = 0;
    return;
  }

  // MOTOR_INVERT membalik arti "maju" tanpa perlu menukar kabel OUT1/OUT2.
  // Aman dilakukan di sini karena rem dan coast sama-sama simetris terhadap
  // arah -- lihat penjelasan di config.h.
#if MOTOR_INVERT
  const bool forward = (wantDirection < 0);
#else
  const bool forward = (wantDirection > 0);
#endif

  if (forward) {
    digitalWrite(PIN_IN1, HIGH);
    digitalWrite(PIN_IN2, LOW);
  } else {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, HIGH);
  }
  _direction = wantDirection;

#if MOTOR_BINARY
  // Mode 1/0: begitu perintah melewati MOTOR_DEADBAND, langsung duty penuh.
  // Arah tetap dihormati -- yang biner hanya besarnya, bukan maju/mundurnya.
  // Lihat alasannya di config.h.
  (void)magnitude;
  ledcWrite(PIN_ENA, MOTOR_PWM_MAX);
#else
  // Petakan rentang perintah yang berguna (deadband..1000) ke rentang duty
  // yang berguna (MOTOR_MIN_DUTY..MOTOR_PWM_MAX), bukan ke 0..MOTOR_PWM_MAX.
  //
  // Kalau dipetakan dari nol, separuh bawah pedal hanya menghasilkan duty
  // yang terlalu kecil untuk memutar motor: mobil diam sambil mendengung dan
  // L298N ikut panas. Dengan pemetaan ini, sentuhan pertama pedal langsung
  // memutar roda dan seluruh jangkauan pedal terasa berguna.
  const uint32_t span = RC_AXIS_MAX - MOTOR_DEADBAND;
  uint32_t usable = magnitude > MOTOR_DEADBAND ? magnitude - MOTOR_DEADBAND : 0;
  uint32_t duty = MOTOR_MIN_DUTY +
                  (usable * (MOTOR_PWM_MAX - MOTOR_MIN_DUTY)) / span;
  if (duty > MOTOR_PWM_MAX) {
    duty = MOTOR_PWM_MAX;
  }
  ledcWrite(PIN_ENA, duty);
#endif
}

void Drive::applyBrakeOutput(uint8_t brake) {
  // IN1=IN2=HIGH menghubung-singkat kedua terminal motor lewat L298N,
  // yang mengerem motor secara dinamis. Duty di ENA menentukan seberapa
  // "rapat" hubung-singkat itu, jadi seberapa kuat pengereman terasa.
  digitalWrite(PIN_IN1, HIGH);
  digitalWrite(PIN_IN2, HIGH);

  // Pemetaan rentang berguna, sama polanya dengan applyMotorOutput(): dari
  // BRAKE_DEADBAND..255 ke BRAKE_MIN_DUTY..MOTOR_PWM_MAX, supaya sentuhan
  // pertama pedal rem langsung terasa alih-alih hanya mendengung.
  const uint32_t span = 255 - BRAKE_DEADBAND;
  uint32_t usable = brake > BRAKE_DEADBAND ? (uint32_t)brake - BRAKE_DEADBAND : 0;
  uint32_t duty = BRAKE_MIN_DUTY +
                  (usable * (MOTOR_PWM_MAX - BRAKE_MIN_DUTY)) / span;
  if (duty > MOTOR_PWM_MAX) {
    duty = MOTOR_PWM_MAX;
  }
  ledcWrite(PIN_ENA, duty);
}

void Drive::writeServoMicros(uint16_t micros) {
  // Batas mekanis absolut. Ini pengaman terakhir untuk linkage kemudi:
  // perintah dari darat tidak pernah bisa menembus batas ini.
  micros = constrain(micros, (uint16_t)SERVO_MIN_US, (uint16_t)SERVO_MAX_US);

  const uint32_t maxDuty = (1UL << SERVO_PWM_BITS) - 1UL;
  const uint32_t periodUs = 1000000UL / SERVO_FREQ_HZ;
  const uint32_t duty = (uint32_t)(((uint64_t)micros * maxDuty) / periodUs);

  ledcWrite(PIN_SERVO, duty);
  _servoUs = micros;
}

uint32_t Drive::motorDuty() const {
  return ledcRead(PIN_ENA);
}
