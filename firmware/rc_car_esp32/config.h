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

// =================================================================
// UNIT_ID -- SATU-SATUNYA BARIS YANG PERLU DIUBAH SAAT FLASH MOBIL
// KE-2 DAN KE-3. Isi 1, 2, atau 3 sesuai mobil mana yang sedang di-flash.
//
// Semua yang bergantung padanya (IP mobil, penyaringan unit_id di
// protokol v3) diturunkan otomatis dari angka ini -- lihat CAR_IP_4 di
// bawah dan filter unit_id di link.cpp. Jangan ada dua mobil dengan
// UNIT_ID yang sama menyala di jaringan yang sama; ground station unit lain
// akan menolak paket dari mobil itu, tapi mobil itu sendiri masih akan
// menjawab siapa pun yang kebetulan memakai unit_id yang sama.
// =================================================================
#define UNIT_ID 2

// ----------------------------------------------------------------- jaringan

#define WIFI_SSID "RCCar"
#define WIFI_PASS "admin.admin"

// IP statis, DITURUNKAN dari UNIT_ID: unit 1 = .50, unit 2 = .51, unit 3 = .52.
// Router GL.iNet memakai subnet 192.168.8.x dengan gateway .1 dan DHCP
// otomatis di rentang .100-.249 -- rentang .50-.52 dipilih supaya tidak
// pernah bentrok dengan situ maupun dengan kamera (.60-.62, lihat
// firmware/rc_cam_esp32/rc_cam_esp32.ino).
// Harus sama dengan network.car_ip di ground/config.yaml (atau biarkan
// ground/config.yaml menurunkannya sendiri lewat kunci `unit:`).
#define CAR_IP_1 192
#define CAR_IP_2 168
#define CAR_IP_3 8
#define CAR_IP_4 (49 + UNIT_ID)

#define GATEWAY_IP_4 1              // gateway = x.x.x.1
#define SUBNET_MASK 255, 255, 255, 0

// Set 1 untuk memakai DHCP, mengabaikan IP statis di atas. Berguna saat
// memakai router biasa yang subnetnya bukan 192.168.137.x
#define USE_DHCP 0

// Jeda antar percobaan sambung ulang. JANGAN dibuat pendek: satu kali
// autentikasi WiFi butuh 1-3 detik untuk selesai atau gagal. Kalau
// WiFi.reconnect() dipanggil sebelum percobaan sebelumnya selesai, driver
// ESP32 akan membanjiri Serial dengan "wifi:sta is connecting, return
// error" lalu "cannot set config" -- bukan berarti SSID/password salah,
// murni karena percobaan lama dan baru bertabrakan.
#define WIFI_RETRY_MS 8000

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
// Arah putaran motor. Set 1 kalau maju/mundur terbalik.
//
// TERUKUR di hardware ini: dengan MOTOR_INVERT 0, perintah maju justru
// membuat mobil mundur. Membaliknya di sini AMAN dan setara dengan menukar
// kabel OUT1/OUT2 -- rem (IN1=IN2=HIGH) dan coast (IN1=IN2=LOW) sama-sama
// simetris, jadi tidak terpengaruh arah, dan jeda balik arah juga tidak
// peduli arah mana yang disebut "maju".
#define MOTOR_INVERT 1

// Ambang nyala motor, skala 0..1000. Di mode biner (MOTOR_BINARY 1) inilah
// titik pedal yang menyalakan motor, jadi perannya jauh lebih penting
// daripada sekadar menolak getaran.
//
// Dinaikkan dari 40 ke 100: di mode biner, 40 berarti sentuhan pedal 4%
// langsung memberi tenaga penuh -- terlalu mudah tersenggol. 100 (10% pedal)
// menuntut tekanan yang disengaja tapi masih terasa responsif.
#define MOTOR_DEADBAND 100

// Kendali PROPORSIONAL (default). Motor mengikuti tekanan pedal secara
// bertahap lewat pemetaan MOTOR_MIN_DUTY..MOTOR_PWM_MAX di applyMotorOutput().
//
// Riwayat: mode ini sempat diganti ke MODE 1/0 (MOTOR_BINARY 1, motor hanya
// mati atau duty penuh) karena Vs L298N 5 V untuk motor 5-6 V menyisakan
// pita duty yang benar-benar menggerakkan mobil hanya sekitar 900..1023 dari
// 1023 -- 12% rentang PWM. Berpura-pura proporsional di pita sesempit itu
// hanya menghasilkan perbedaan kecepatan yang tidak terasa, sekaligus
// membuat mobil sering tidak mau jalan di separuh bawah pedal. Alasan itu
// masih valid untuk hardware ini kalau suatu saat perlu dipakai lagi.
//
// Set 1 untuk kembali ke mode biner itu. Set 0 (sekarang) untuk proporsional
// -- pilihan yang lebih masuk akal setelah Vs dinaikkan ke ~7,5-8 V atau
// driver diganti ke TB6612FNG, karena saat itu pita duty yang berguna
// kembali lebar. Kalau dipakai lagi di hardware lama (Vs masih 5 V), pita
// sempit di atas kemungkinan akan terasa lagi -- itu bukan bug.
#define MOTOR_BINARY 0

// Duty minimum saat motor MULAI bergerak. Rentang perintah yang berguna
// dipetakan ke MOTOR_MIN_DUTY..MOTOR_PWM_MAX, bukan 0..MOTOR_PWM_MAX,
// supaya sentuhan pertama pedal langsung memutar roda alih-alih mendengung.
//
// TERUKUR DUA KALI, dan angka keduanya yang dipakai:
//   - roda di udara  : motor mulai berputar di duty ~716
//   - roda di lantai : mobil baru benar-benar jalan di sekitar duty ~900
//
// Angka tanpa beban menyesatkan. Gesekan ban, gardan, dan berat mobil
// menaikkan ambangnya jauh. Yang dipakai di sini adalah kondisi nyata
// saat mengemudi, supaya pedal bagian bawah tidak lagi terasa mati.
//
// Angka setinggi ini BUKAN normal -- penyebabnya Vs L298N hanya 5 V untuk
// motor 5-6 V, sehingga setelah drop L298N ~2,5 V motor cuma menerima
// ~2,5 V pada duty penuh. Akibatnya hanya sekitar 30% rentang PWM yang
// berguna, dan itu pula yang membuat kenaikan tegangan terasa tidak linear.
// Perbaikan sebenarnya ada di hardware (naikkan Vs ke ~7,5-8 V, atau ganti
// ke driver MOSFET seperti TB6612FNG yang drop-nya hanya ~0,5 V), bukan di
// angka ini. Nilai ini membuat rentang yang tersisa tetap terpakai penuh.
#define MOTOR_MIN_DUTY 900

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

// Durasi maksimum pulsa dorong-balik (reverse pulse / "plugging") saat rem
// diinjak ketika mobil sedang bergerak. Mobil ini TIDAK punya sensor
// kecepatan roda, jadi tidak ada cara untuk tahu kapan mobil benar-benar
// berhenti -- satu-satunya pengaman yang tersedia murni berbasis waktu:
// dorong sebentar ke arah berlawanan lalu paksa coast (OFF), mengandalkan
// durasi pendek + inersia mobil supaya ia melambat tanpa sempat benar-benar
// membalik arah gerak. JANGAN naikkan angka ini sembarangan -- makin lama
// pulsa mundur diberikan, makin besar risiko mobil benar-benar bergerak
// mundur sungguhan, bukan sekadar mengerem.
#define BRAKE_REVERSE_PULSE_MS 500

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
// Ketiganya TERUKUR di hardware lewat konsol serial, bukan tebakan:
//   1200 us = mentok KANAN
//   1400 us = lurus
//   1600 us = mentok KIRI
//
// SIMETRIS: 200 us ke kiri, 200 us ke kanan. Ini hasil kalibrasi ulang
// setelah linkage disetel; pengukuran sebelumnya (1250/1350/1500) tidak
// simetris dan membuat radius belok kiri dan kanan berbeda. Sekarang
// keduanya sama.
//
// drive.cpp tetap menghitung kedua sisi secara TERPISAH, jadi kalau suatu
// saat linkage bergeser lagi dan hasilnya tidak simetris, tulis saja apa
// adanya -- kodenya tidak mengasumsikan simetri.
//
// Cara mengukur ulang: konsol serial, "test on" lalu "servo <us>" naik/turun
// bertahap sampai servo mendengung menahan di ujung, mundur 25 us dari titik
// itu. Jangan lupa "test off" setelah selesai.
#define SERVO_MIN_US 1000           // mentok KANAN
#define SERVO_CENTER_US 1200        // lurus
#define SERVO_MAX_US 1500           // mentok KIRI

// Arah belok. Set 1 kalau stir kanan justru membelokkan roda ke kiri.
//
// TERUKUR di hardware ini: protokol memakai steer positif = kanan, dan
// drive.cpp memetakan nilai positif ke SERVO_MAX_US (angka us lebih besar).
// Tapi di sini KANAN justru ada di 1250 us -- angka lebih KECIL. Tanpa
// pembalikan ini, stir kanan akan membelokkan roda ke kiri.
//
// Dibalik di firmware, bukan lewat steering.invert di config.yaml, karena
// ini fakta pemasangan hardware mobil -- bukan preferensi rasa menyetir.
// Biarkan steering.invert di sisi darat tetap bebas untuk keperluan lain.
#define SERVO_INVERT 1

// ----------------------------------------------------------------- failsafe

// DIMATIKAN atas permintaan, karena mobil ini kecil, bertenaga rendah, dan
// dipakai di track khusus. Set 1 untuk menyalakannya lagi.
//
// Saat 0: kalau paket kontrol berhenti, mobil MEMPERTAHANKAN perintah
// terakhir tanpa batas waktu. Kalau tautan putus saat gas sedang ditekan,
// mobil terus melaju dengan gas itu sampai paket kembali atau baterai
// dicabut. Itu konsekuensi yang disengaja di sini, bukan kelalaian.
//
// Yang TIDAK ikut dimatikan: aturan arming. Mobil tetap menyala dalam
// keadaan disarmed dan tetap butuh transisi flag ARMED 0->1 dari ground
// station sebelum motor mau bergerak. Itu mekanisme terpisah dan tetap
// berguna -- lihat docs/protocol.md bagian 5.
#define FAILSAFE_ENABLED 0

// Tidak ada paket kontrol valid selama ini -> motor netral, servo tengah,
// status kembali disarmed. Hanya berlaku kalau FAILSAFE_ENABLED = 1.
// Harus sama dengan FAILSAFE_TIMEOUT di fake_car.py
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
// Jeda cetak status berkala. 0 = MATI (default sekarang).
//
// Dimatikan bukan karena membebani -- satu baris status ~130 karakter di
// 115200 baud memakan ~11 ms, dua kali per detik berarti sekitar 2% waktu
// serial. Itu tidak akan membuat ESP32 kewalahan.
//
// Dimatikan karena sudah tidak perlu: konsol punya perintah "status" yang
// mencetak keadaan lengkap saat Anda minta. Mencetak terus-menerus hanya
// membuat Serial Monitor sulit dibaca saat Anda sedang mengetik perintah.
//
// Isi 500 (atau 200) kalau sedang melacak masalah dan ingin melihat nilai
// berjalan tanpa mengetik apa-apa.
#define SERIAL_STATUS_MS 0
