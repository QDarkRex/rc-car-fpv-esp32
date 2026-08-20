// config.h — seluruh setelan firmware mobil ada di berkas ini.
//
// Yang perlu Anda ubah sebelum flash pertama kali:
//   1. WIFI_SSID dan WIFI_PASS  -> nama dan sandi hotspot LattePanda
//   2. VBAT_DIVIDER_RATIO       -> setelah mengukur resistor pembagi Anda
//
// Catatan penting soal pembagian tugas:
// Kurva gas, deadzone, trim, dan batas kecepatan TIDAK ada di sini. Semua itu
// hidup di sisi darat (ground/config.yaml) supaya bisa diubah tanpa flash
// ulang. Yang ada di sini hanya batas keselamatan absolut milik hardware.

#pragma once

// ----------------------------------------------------------------- jaringan

#define WIFI_SSID "RCCar"
#define WIFI_PASS "admin.admin"

// IP statis. Nilai default cocok untuk Windows Mobile Hotspot yang selalu
// memakai subnet 192.168.137.x dengan gateway .1
// Harus sama dengan network.car_ip di ground/config.yaml
#define CAR_IP_1 192
#define CAR_IP_2 168
#define CAR_IP_3 137
#define CAR_IP_4 50

#define GATEWAY_IP_4 1              // gateway = x.x.x.1
#define SUBNET_MASK 255, 255, 255, 0

// Set 1 untuk memakai DHCP, mengabaikan IP statis di atas. Berguna saat
// memakai router biasa yang subnetnya bukan 192.168.137.x
#define USE_DHCP 0

#define WIFI_RETRY_MS 500           // jeda antar percobaan sambung ulang

// ----------------------------------------------------------------- pin

// L298N. Jumper ENA di board WAJIB DILEPAS, kalau tidak PWM tidak berefek
// dan motor hanya bisa mati atau kencang penuh.
#define PIN_ENA 4                   // PWM kecepatan
// GPIO 15 adalah strapping pin (menentukan verbosity log boot), tapi aman
// dipakai untuk IN1: motor tidak mungkin berputar selama ENA masih rendah
// di awal boot, jadi keadaan IN1 saat itu tidak berpengaruh ke apa pun.
// JANGAN pindahkan ENA ke pin strapping manapun -- ENA yang salah keadaan
// saat boot langsung berarti duty motor tidak tentu.
#define PIN_IN1 15                  // arah
#define PIN_IN2 22                  // arah

#define PIN_SERVO 13                // sinyal servo digital

// Pembacaan tegangan baterai. WAJIB pin ADC1 (32-39), karena ADC2 tidak bisa
// dipakai bersamaan dengan WiFi di ESP32. GPIO34 juga input-only, jadi tidak
// mungkin tak sengaja menjadi output.
#define PIN_VBAT 34

#define PIN_LED 2                   // LED onboard, indikator status

// ----------------------------------------------------------------- motor

// Frekuensi PWM motor. 16 kHz hampir di luar jangkauan pendengaran, tapi
// masih dalam batas kemampuan switching L298N. L298N memakai transistor
// bipolar yang lambat; di atas ~20 kHz rugi switching-nya membesar dan
// driver cepat panas. Jangan naikkan tanpa alasan.
#define MOTOR_PWM_FREQ_HZ 16000
#define MOTOR_PWM_BITS 10
#define MOTOR_PWM_MAX ((1 << MOTOR_PWM_BITS) - 1)   // 1023

// Di bawah nilai perintah ini motor dianggap berhenti. Motor DC lewat L298N
// tidak akan berputar pada duty rendah -- hanya mendengung dan panas.
#define MOTOR_DEADBAND 60           // dari skala 0..1000

// Duty minimum saat motor MULAI bergerak. Rentang perintah yang berguna
// dipetakan ke MOTOR_MIN_DUTY..MOTOR_PWM_MAX, bukan 0..MOTOR_PWM_MAX,
// supaya sentuhan pertama pedal langsung memutar roda alih-alih mendengung.
// Naikkan kalau motor Anda baru mau jalan di duty lebih tinggi.
#define MOTOR_MIN_DUTY 300

// Batas perubahan perintah motor per detik, dalam satuan skala 0..1000.
// Ini lapis kedua setelah slew_rate di sisi darat -- sengaja dibuat lebih
// longgar agar tidak melawan setelan darat, tapi tetap menahan lonjakan
// arus ekstrem kalau config darat diisi terlalu agresif.
#define MOTOR_SLEW_PER_SEC 4000

// Jeda mati total saat motor berbalik arah. Mencegah kedua sisi H-bridge
// menyala bersamaan (shoot-through) yang bisa merusak L298N.
// Jeda yang sama juga berlaku saat keluar dari mode rem menuju gerak, dengan
// alasan yang sama: IN1/IN2 tidak boleh sama-sama HIGH lalu langsung sama-sama
// dipakai untuk arah tanpa jeda mati di antaranya.
#define REVERSE_GUARD_MS 40

// ----------------------------------------------------------------- rem

// Di bawah nilai perintah ini rem dianggap tidak diinjak. Skala 0..255,
// sama seperti field `brake` di protokol.
#define BRAKE_DEADBAND 20

// Duty ENA minimum saat mode rem MULAI aktif, dengan alasan yang sama seperti
// MOTOR_MIN_DUTY: rentang perintah rem yang berguna (deadband..255) dipetakan
// ke BRAKE_MIN_DUTY..MOTOR_PWM_MAX, bukan 0..MOTOR_PWM_MAX, supaya sentuhan
// pertama pedal rem langsung menghubung-singkat motor, bukan mendengung.
#define BRAKE_MIN_DUTY 300

// ----------------------------------------------------------------- servo

// 50 Hz aman untuk semua servo. Servo digital umumnya sanggup 200-333 Hz dan
// terasa jauh lebih tajam -- naikkan HANYA setelah memastikan spesifikasi
// servo Anda mengizinkan. Servo analog akan rusak pada frekuensi tinggi.
#define SERVO_FREQ_HZ 50
#define SERVO_PWM_BITS 16

// BATAS MEKANIS ABSOLUT. Ini pengaman linkage: berapa pun perintah dari
// darat, servo tidak akan pernah menabrak ujung mekanisnya.
//
// Cara menyetel: mulai dari nilai sempit (1300/1700), lalu lebarkan sedikit
// demi sedikit sambil mendengarkan. Begitu servo mendengung menahan di ujung,
// Anda sudah kelewatan -- mundur 50 us. Servo yang menahan di ujung akan
// panas dan rusak dalam hitungan menit.
#define SERVO_MIN_US 1100           // belok penuh ke satu sisi
#define SERVO_CENTER_US 1500        // lurus
#define SERVO_MAX_US 1900           // belok penuh ke sisi lain

// ----------------------------------------------------------------- failsafe

// Tidak ada paket kontrol valid selama ini -> motor netral, servo tengah,
// status kembali disarmed. Harus sama dengan FAILSAFE_TIMEOUT di fake_car.py
#define FAILSAFE_TIMEOUT_MS 300

// ----------------------------------------------------------------- baterai

// Pembagi tegangan: VBAT -- R1 -- (titik ukur ke GPIO34) -- R2 -- GND
// Rasio = (R1 + R2) / R2. Untuk R1=100k dan R2=22k -> 122/22 = 5.545
//
// UKUR resistor Anda dengan multimeter dan sesuaikan angka ini. Toleransi
// resistor 5% membuat pembacaan meleset sampai 0,8 V pada paket 4S, dan
// itu cukup untuk membuat peringatan baterai jadi tidak berguna.
#define VBAT_DIVIDER_RATIO 5.545f

// Ambang peringatan untuk 4S LiPo. 14,0 V = 3,50 V per sel; di bawah ini
// sel mulai mengalami kerusakan permanen.
#define VBAT_LOW_MV 14000

#define VBAT_SAMPLES 16             // rata-rata, meredam noise dari motor

// ----------------------------------------------------------------- serial

#define SERIAL_BAUD 115200
#define SERIAL_STATUS_MS 500        // jeda cetak status; 0 untuk mematikan
