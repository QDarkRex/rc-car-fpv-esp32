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
  _brakeDirection = 0;
  _brakePulseStartMs = 0;
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

  // --- prioritas 1: rem, sebagai "reverse pulse" (plugging): dorong
  // sebentar ke arah BERLAWANAN dari arah gerak sebelum rem diinjak, lalu
  // paksa coast. Menang atas throttle setiap kali brake di atas ambang --
  // lihat docs/protocol.md soal kenapa rem punya field sendiri.
  if (wantBrake) {
    if (now < _reverseGuardUntilMs) {
      coast();
      return;
    }
    if (!_braking) {
      // Baru masuk mode rem: catat arah gerak SEBELUM direm -- ini yang
      // menentukan arah pulsa dorong-balik nanti, bukan _direction yang
      // sebentar lagi dinolkan.
      _brakeDirection = _direction;
      _direction = 0;
      _braking = true;
      if (_brakeDirection != 0) {
        // Mobil memang sedang bergerak: matikan H-bridge dulu dan beri jeda
        // balik arah sebelum mulai mendorong ke arah berlawanan. Tanpa jeda
        // ini, transisi dari satu sisi HIGH langsung ke arah kebalikannya
        // berisiko shoot-through yang sama seperti berbalik arah biasa.
        coast();
        _reverseGuardUntilMs = now + REVERSE_GUARD_MS;
        // Belum mulai menghitung pulsa -- baru dimulai iterasi berikutnya,
        // setelah guard di atas selesai. Lihat cabang _braking di bawah.
        _brakePulseStartMs = 0;
        return;
      }
      // Mobil sudah diam saat rem diinjak: TIDAK PERNAH ada pulsa mundur.
      // Cukup coast, tidak ada apa pun untuk "diperlambat".
      coast();
      return;
    }
    if (_brakeDirection == 0) {
      // Sudah dalam mode rem tapi mobil memang sudah diam sejak awal: tetap
      // diam, tidak ada pulsa.
      coast();
      return;
    }
    // Sudah dalam mode rem, mobil sedang diperlambat lewat reverse pulse.
    if (_brakePulseStartMs == 0) {
      _brakePulseStartMs = now;
    }
    if (now - _brakePulseStartMs >= BRAKE_REVERSE_PULSE_MS) {
      // Jendela pulsa sudah habis. BERHENTI mendorong mundur -- durasi
      // pendek + inersia sudah cukup untuk memperlambat mobil tanpa
      // benar-benar membalik arah gerak; mendorong lebih lama dari ini
      // hanya menambah risiko mobil benar-benar mundur. Cukup diam sampai
      // rem dilepas.
      coast();
      return;
    }
    applyBrakeOutput(_targetBrake, _brakeDirection);
    return;
  }

  // --- keluar dari mode rem menuju gerak: jeda balik arah berlaku lagi di
  // sini juga, dengan alasan sama seperti di atas tapi arah terbalik.
  if (_braking) {
    coast();
    _braking = false;
    _direction = 0;
    _brakeDirection = 0;
    _brakePulseStartMs = 0;
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

void Drive::applyBrakeOutput(uint8_t brake, int8_t originalDirection) {
  // Reverse pulse (plugging): alih-alih menghubung-singkat motor
  // (IN1=IN2=HIGH), sisi ini mendorong motor ke arah BERLAWANAN dari
  // originalDirection -- arah mobil TEPAT SEBELUM rem diinjak. Ini yang
  // membuat rem terasa lebih tegas daripada short-brake biasa. Durasi
  // dorongan ini dibatasi ketat di update() (BRAKE_REVERSE_PULSE_MS di
  // config.h) supaya mobil melambat tanpa sempat benar-benar berbalik arah.
  //
  // Sama seperti applyMotorOutput(), MOTOR_INVERT harus dihormati di sini
  // supaya arah fisik "lawan arah" konsisten dengan pembalikan yang sama
  // yang dipakai untuk maju/mundur normal -- jangan hardcode HIGH/LOW tanpa
  // mempertimbangkan MOTOR_INVERT.
  // Ini persis pemetaan MOTOR_INVERT di applyMotorOutput(), diterapkan pada
  // ARAH LAWAN dari originalDirection (bukan originalDirection itu sendiri)
  // -- makanya perbandingannya tampak "terbalik" dibanding applyMotorOutput.
#if MOTOR_INVERT
  const bool forward = (originalDirection > 0);
#else
  const bool forward = (originalDirection < 0);
#endif
  if (forward) {
    digitalWrite(PIN_IN1, HIGH);
    digitalWrite(PIN_IN2, LOW);
  } else {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, HIGH);
  }

  // Pemetaan rentang berguna, sama polanya dengan applyMotorOutput(): dari
  // BRAKE_DEADBAND..255 ke BRAKE_MIN_DUTY..MOTOR_PWM_MAX, supaya sentuhan
  // pertama pedal rem langsung terasa alih-alih hanya mendengung. Pemetaan
  // ini TIDAK berubah dari versi short-brake -- hanya arah H-bridge di atas
  // yang berubah.
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
