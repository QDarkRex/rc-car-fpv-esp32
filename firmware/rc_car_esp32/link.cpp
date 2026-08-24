#include "link.h"

#include <WiFi.h>

void CarLink::begin() {
  analogReadResolution(12);
  _lastValidMs = millis() - FAILSAFE_TIMEOUT_MS - 1;  // mulai dalam failsafe
  connectWifi();
  _udp.begin(RC_CONTROL_PORT);
  Serial.printf("[LINK] mendengarkan UDP :%d\n", RC_CONTROL_PORT);
}

void CarLink::connectWifi() {
  WiFi.mode(WIFI_STA);

  // WAJIB. Dengan power save aktif (default), radio tidur di antara beacon
  // dan latensi melonjak acak sampai ratusan milidetik. Untuk kendali
  // real-time itu terasa seperti mobil yang tiba-tiba tidak menurut.
  WiFi.setSleep(false);

#if !USE_DHCP
  IPAddress local(CAR_IP_1, CAR_IP_2, CAR_IP_3, CAR_IP_4);
  IPAddress gateway(CAR_IP_1, CAR_IP_2, CAR_IP_3, GATEWAY_IP_4);
  IPAddress subnet(SUBNET_MASK);
  if (!WiFi.config(local, gateway, subnet, gateway)) {
    Serial.println("[LINK] gagal menerapkan IP statis, memakai DHCP");
  }
#endif

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[LINK] menyambung ke \"%s\"...\n", WIFI_SSID);
  _lastWifiAttemptMs = millis();
}

void CarLink::serviceWifi() {
  const bool nowConnected = (WiFi.status() == WL_CONNECTED);

  if (nowConnected != _wifiConnected) {
    _wifiConnected = nowConnected;
    if (nowConnected) {
      Serial.print("[LINK] tersambung, IP ");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println("[LINK] WiFi terputus");
    }
  }

  if (!nowConnected && (millis() - _lastWifiAttemptMs) > WIFI_RETRY_MS) {
    _lastWifiAttemptMs = millis();
    WiFi.reconnect();
  }
}

bool CarLink::acceptSequence(uint16_t seq) {
  if (!_hasSeq) {
    _hasSeq = true;
    _lastSeq = seq;
    return true;
  }

  // Selisih dihitung sebagai int16_t agar pembungkusan di 65535 tertangani
  // sendiri tanpa penanganan khusus.
  const int16_t diff = (int16_t)(seq - _lastSeq);

  if (diff > 0) {
    _lastSeq = seq;
    return true;
  }

  // Lompatan mundur yang sangat jauh berarti sisi darat baru saja dijalankan
  // ulang dan nomor urutnya mulai dari awal lagi. Kalau ini tidak diterima,
  // mobil akan menolak SEMUA paket selamanya sampai di-boot ulang.
  if (diff < -1000) {
    Serial.println("[LINK] nomor urut mundur jauh - sisi darat restart");
    _lastSeq = seq;
    return true;
  }

  // Sisanya: paket kembar atau paket yang datang terlambat. Mengeksekusi
  // perintah basi lebih berbahaya daripada melewatkannya.
  _staleCount++;
  return false;
}

void CarLink::receivePackets() {
  int size;
  while ((size = _udp.parsePacket()) > 0) {
    const int length = _udp.read(_buffer, sizeof(_buffer));
    if (length <= 0) {
      continue;
    }

    if (!rc_validate_control(_buffer, (size_t)length)) {
      // Paket rusak TIDAK menyegarkan pewaktu failsafe.
      _badCount++;
      continue;
    }

    ControlPacket packet;
    memcpy(&packet, _buffer, sizeof(packet));

    if (packet.unit_id != UNIT_ID) {
      // Paket sehat (magic/versi/CRC benar) tapi ditujukan ke mobil lain --
      // kemungkinan besar ground station unit lain yang masih dalam fase
      // discovery broadcast (lihat docs/protocol.md bagian 6 dan 7). Dibuang
      // SEPERTI paket rusak: TIDAK menyegarkan _lastValidMs, supaya mobil
      // yang salah kunci tidak diam-diam terlihat "sehat" di sisi darat yang
      // salah itu. Dihitung terpisah dari _badCount supaya konsol bisa
      // membedakan gangguan protokol dari cross-control murni.
      _foreignCount++;
      continue;
    }

    if (!acceptSequence(packet.seq)) {
      continue;
    }

    _rxCount++;
    _peerIp = _udp.remoteIP();
    _peerPort = _udp.remotePort();
    _hasPeer = true;

    handleControl(packet);
  }
}

void CarLink::handleControl(const ControlPacket& packet) {
  _lastValidMs = millis();

  // Failsafe murni soal kesehatan tautan. Paket valid berarti tautan hidup.
  // Boleh-tidaknya motor bergerak diatur terpisah oleh flag armed.
  _failsafe = false;

  const bool armedFlag = (packet.flags & RC_FLAG_ARMED) != 0;
  const bool calibrationFlag = (packet.flags & RC_FLAG_SERVO_CALIBRATION) != 0;
  const bool calibrationValid = calibrationFlag && !armedFlag && !_armed &&
                                packet.throttle == 0 && packet.brake == 0;
  // A packet carrying the calibration bit can never participate in arming,
  // even if a malformed sender also sets ARMED.
  const bool normalArmedFlag = armedFlag && !calibrationFlag;
  _servoCalibration = calibrationValid;
  _servoSteer = calibrationValid ? constrain(packet.steer, -RC_AXIS_MAX, RC_AXIS_MAX) : 0;

  // A calibration flag with any motor/armed combination is rejected and
  // immediately loses its steering-only privilege.
  _steer = packet.steer;
  _throttle = packet.throttle;
  _brake = packet.brake;
  if (normalArmedFlag) {
    // Hanya transisi 0 -> 1 yang meng-arm. Flag yang terus bernilai 1
    // TIDAK meng-arm ulang dengan sendirinya.
    if (!_prevArmedFlag) {
      _armed = true;
      Serial.println("[LINK] ARMED");
    }
  } else if (_armed) {
    _armed = false;
    Serial.println("[LINK] disarmed");
  }
  _prevArmedFlag = normalArmedFlag;

  // Balas telemetri langsung pada paketnya, bukan dari timer bebas, supaya
  // seq_echo terkirim segera dan RTT yang diukur sisi darat benar-benar
  // waktu tempuh pulang-pergi. Lihat docs/protocol.md bagian 3.
  if ((packet.seq % RC_TELEMETRY_EVERY_N) == 0) {
    sendTelemetry(packet.seq);
  }
}

void CarLink::sendTelemetry(uint16_t seqEcho) {
  if (!_hasPeer || !_wifiConnected) {
    return;
  }

  TelemetryPacket telemetry;
  memset(&telemetry, 0, sizeof(telemetry));
  telemetry.magic0 = RC_TELE_MAGIC0;
  telemetry.magic1 = RC_TELE_MAGIC1;
  telemetry.version = RC_PROTOCOL_VERSION;
  telemetry.unit_id = UNIT_ID;
  telemetry.seq_echo = seqEcho;
  telemetry.vbat_mv = _vbatMv;
  telemetry.rssi = (int8_t)constrain(WiFi.RSSI(), -128, 127);
  telemetry.uptime_ms = millis();

  uint8_t flags = 0;
  if (_armed) {
    flags |= RC_TFLAG_ARMED;
  }
  if (_failsafe) {
    flags |= RC_TFLAG_FAILSAFE;
  }
  if (lowBattery()) {
    flags |= RC_TFLAG_LOWBATT;
  }
  telemetry.flags = flags;

  rc_finalize_telemetry(&telemetry);

  _udp.beginPacket(_peerIp, _peerPort);
  _udp.write((const uint8_t*)&telemetry, sizeof(telemetry));
  _udp.endPacket();
}

void CarLink::sampleBattery() {
  const uint32_t now = millis();
  if (now - _lastBatteryMs < 100) {
    return;
  }
  _lastBatteryMs = now;

  // analogReadMilliVolts memakai kalibrasi eFuse pabrik, jadi hasilnya jauh
  // lebih linear daripada analogRead() mentah yang terkenal melenceng di
  // ujung atas dan bawah rentang.
  uint32_t sum = 0;
  for (int i = 0; i < VBAT_SAMPLES; i++) {
    sum += analogReadMilliVolts(PIN_VBAT);
  }
  const uint32_t pinMv = sum / VBAT_SAMPLES;
  _vbatMv = (uint16_t)constrain((int32_t)(pinMv * VBAT_DIVIDER_RATIO), 0, 65535);
}

void CarLink::update() {
  serviceWifi();
  receivePackets();
  sampleBattery();

  // Kalibrasi servo selalu punya timeout sendiri, termasuk pada instalasi
  // yang sengaja mematikan failsafe motor lewat FAILSAFE_ENABLED. Kalau
  // wizard, laptop, atau WiFi berhenti mengirim, hak steering-only ini tidak
  // boleh tertinggal aktif tanpa batas.
  if (_servoCalibration && (millis() - _lastValidMs) > FAILSAFE_TIMEOUT_MS) {
    _servoCalibration = false;
    _servoSteer = 0;
  }

#if !FAILSAFE_ENABLED
  // Failsafe dimatikan lewat config.h: perintah terakhir dipertahankan
  // walaupun paket berhenti. Lihat penjelasan lengkap di config.h.
  return;
#else
  if ((millis() - _lastValidMs) > FAILSAFE_TIMEOUT_MS) {
    if (!_failsafe) {
      Serial.println("[LINK] FAILSAFE - paket kontrol putus");
    }
    _failsafe = true;
    _armed = false;
    _steer = 0;
    _throttle = 0;
    _brake = 0;
    _servoCalibration = false;
    _servoSteer = 0;

    // KUNCI KE POSISI TINGGI, bukan direset ke false.
    //
    // Kalau direset ke false, paket pertama yang tiba setelah WiFi pulih --
    // yang masih membawa ARMED=1 dari sebelum putus -- akan terlihat seperti
    // transisi 0->1 baru, dan mobil arm sendiri lalu langsung melaju.
    // Dengan dikunci tinggi, sisi darat wajib mengirim ARMED=0 dulu.
    //
    // Ini bukan kehati-hatian teoretis: bug persis ini sempat ada di
    // fake_car.py dan tertangkap pengujian. Lihat docs/protocol.md bagian 5.
    _prevArmedFlag = true;
  }
#endif
}
