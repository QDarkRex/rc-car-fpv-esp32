# Perakitan dan Pengkabelan

Dokumen ini mencakup daftar komponen, skema daya, pengkabelan tiap modul,
cara flash modul kamera (XIAO ESP32S3 Sense / AI-Thinker ESP32-CAM), dan
checklist perakitan.

Baca **bagian 2 (Daya)** sampai selesai sebelum membeli apa pun. Di situlah
letak sebagian besar cara proyek seperti ini gagal.

---

## 1. Daftar komponen

### Sudah Anda miliki

| Komponen | Peran |
|---|---|
| LattePanda | Ground station, tempat stir PXN dicolok |
| Stir PXN V9 + pedal | Perangkat kendali |
| ESP32 dev module | Otak mobil: motor + servo + WiFi |
| Seeed XIAO ESP32S3 Sense | Kamera FPV |
| L298N | Driver motor |
| Servo digital | Kemudi roda depan |
| LiPo 4S 850 mAh | Catu daya |

### Yang perlu ditambahkan

| Komponen | Spesifikasi | Kenapa |
|---|---|---|
| Step-down #1 | 4S → 12 V, **≥3 A** (XL4015 / LM2596) | Catu motor lewat L298N |
| Step-down #2 | 4S → 5 V, **≥3 A** (XL4015 / MP1584 3 A) | Servo + kedua ESP32 |
| Elko 1000 µF / 25 V | low-ESR | Di jalur 5 V servo |
| Elko 470 µF / 16 V | low-ESR | Di jalur 5 V/3V3 XIAO ESP32S3 Sense |
| Elko 470 µF / 25 V | low-ESR | Di terminal Vs L298N |
| Keramik 100 nF | ×5 | Peredam noise motor dan bypass |
| Resistor 100 kΩ dan 22 kΩ | 1% kalau ada | Pembagi tegangan telemetri |
| Alarm LiPo / lipo buzzer | untuk 4S | Peringatan tegangan yang tidak bergantung software |

XIAO ESP32S3 Sense punya USB-C bawaan, jadi adapter USB-serial FTDI/CH340
**tidak lagi diperlukan untuk kamera** (dulu wajib untuk AI-Thinker
ESP32-CAM). Kalau Anda masih menyimpan AI-Thinker ESP32-CAM sebagai modul
cadangan, siapkan tetap adapter FTDI/CH340 dengan **logic 3,3 V** untuknya
saja — lihat bagian 7.

Belilah step-down yang **bisa disetel** (ada trimpot) dan setel tegangannya
dengan multimeter **sebelum** disambungkan ke apa pun.

---

## 2. Daya — bagian terpenting dokumen ini

### Kenapa 5 V TIDAK boleh diambil dari L298N

Pin 5 V pada board L298N berasal dari regulator linear 78M05. Batas praktisnya
sekitar **0,5 A**, dan pada input 12 V ia harus membuang (12−5) × I sebagai
panas di board kecil tanpa heatsink yang memadai.

Beban Anda:

| Beban | Rata-rata | Puncak |
|---|---:|---:|
| ESP32 dev module (WiFi aktif) | ~150 mA | ~250 mA |
| XIAO ESP32S3 Sense (WiFi + kamera) | ~150 mA¹ | ~300 mA² |
| Servo digital (bergerak / menahan) | ~100 mA | **1500–2500 mA** |
| **Total** | **~400 mA** | **~3050 mA** |

¹ Spesifikasi vendor menyebut ~100–150 mA saat WiFi aktif; kamera menambah
sedikit lagi. Angka gabungan kamera+WiFi belum diukur langsung di proyek
ini.
² Perkiraan konservatif, dipertahankan setinggi angka lama AI-Thinker
ESP32-CAM (~310 mA) sampai ada pengukuran nyata — lebih aman melebih-lebihkan
puncak arus daripada menganggapnya rendah.

Puncaknya enam kali lipat kemampuan regulator itu. Gejalanya khas: setiap kali
Anda memutar stir, tegangan 5 V anjlok, modul kamera reboot, dan video mati
beberapa detik. Diteruskan cukup lama, regulatornya terbakar.

Servo adalah beban paling ganas di sini karena arus stall-nya besar dan
munculnya mendadak — persis saat Anda paling butuh kendali.

### Skema daya yang dipakai

```
                     LiPo 4S 850 mAh
              (14,8 V nominal / 16,8 V penuh)
                            |
              +-------------+-------------+----------------+
              |                           |                |
              |                           |                |
        [Step-down #1]              [Step-down #2]    [Pembagi R]
         4S -> 12 V                  4S -> 5 V         100k / 22k
         >= 3 A                      >= 3 A                |
              |                           |                |
              |                    +------+------+         v
              v                    |      |      |     GPIO34 ESP32
        L298N  Vs  ------+         |      |      |    (telemetri baterai)
        L298N  GND       |         |      |      |
        L298N  5V --------+        v      v      v
        (logika,          |    Servo   ESP32   kamera
         WAJIB!)          |      |     dev        |
                    [470uF/25V]  |               [470uF] + [100nF]
                                 |
                            [1000uF/25V]

        L298N: jumper ENA DILEPAS. Jumper 5V (regulator) DILEPAS, TAPI pin
        5V header tetap disambung ke step-down #2 -- itu jalur daya logika
        chip L298N sendiri, bukan sekadar keluaran regulator yang dicabut.
        Dibiarkan mengambang = H-bridge tidak pernah aktif sama sekali.

        SEMUA GND disatukan di SATU titik dekat terminal negatif baterai
        (star ground) -- termasuk GND kedua step-down, L298N, servo,
        kedua ESP32, dan sisi bawah pembagi tegangan.
```

### Catatan tiap cabang

**Step-down #1 (12 V untuk motor).** Ada di sana untuk melindungi *motor*,
bukan L298N — L298N sendiri sanggup menerima hingga 35 V. Kalau motor Anda
memang motor 12 V, jangan langsung diberi 16,8 V dari 4S penuh.

L298N sendiri menjatuhkan sekitar **2–2,5 V** di transistor keluarannya, jadi
motor menerima sekitar 9,5–10 V pada beban penuh. Ini normal untuk L298N dan
bukan tanda kerusakan.

**Step-down #2 (5 V untuk elektronik).** Elko 1000 µF dipasang **sedekat
mungkin dengan konektor servo**, bukan di dekat step-down. Gunanya menyediakan
arus sesaat saat servo menyentak, sebelum step-down sempat menanggapi.

**Kalau ingin lebih aman lagi:** pakai step-down ketiga khusus untuk kedua
ESP32, terpisah dari servo. Dengan begitu lonjakan arus servo tidak menyentuh
rel elektronik sama sekali. Dengan dua step-down saja, elko besar itu wajib.

**Pembagi tegangan.** Menarik 16,8 V / 122 kΩ ≈ 138 µA terus-menerus. Itu
sekitar 3,3 mAh per hari — tidak berpengaruh saat dipakai, tapi **cabut
baterai saat disimpan**, karena LiPo yang dibiarkan terhubung berminggu-minggu
akan turun sampai rusak.

### Perkiraan waktu jalan

4S 850 mAh dengan motor gerak dan dua ESP32 realistisnya **5–8 menit**. Ini
batas kapasitas baterai, bukan sesuatu yang bisa diperbaiki dari sisi program.
Kalau kurang, satu-satunya jalan adalah paket baterai lebih besar.

Jangan pernah menguras 4S di bawah **14,0 V** (3,50 V per sel) saat dipakai.
HUD akan memberi peringatan merah di angka itu.

---

## 3. ESP32 dev module — pemetaan pin

| Fungsi | GPIO | Menuju | Catatan |
|---|---:|---|---|
| PWM kecepatan | **4** | L298N `ENA` | jumper ENA harus dilepas |
| Arah 1 | **15** | L298N `IN1` | strapping pin, lihat catatan di bawah |
| Arah 2 | **22** | L298N `IN2` | |
| Sinyal servo | **13** | kabel sinyal servo (oranye/putih) | |
| Sensor baterai | **34** | titik tengah pembagi | input-only, ADC1 |
| LED status | **2** | LED onboard | |
| 5 V | `VIN`/`5V` | step-down #2 | |
| Ground | `GND` | star ground | |

Pin-pin ini dipilih dengan alasan:

- **GPIO 34 wajib ADC1.** ADC2 tidak bisa dipakai bersamaan dengan WiFi di
  ESP32 — pembacaan akan gagal begitu radio aktif. GPIO 34 juga input-only,
  jadi mustahil tak sengaja menjadi output yang menabrak pembagi tegangan.
- **GPIO 6–11 dihindari** karena terpakai untuk flash internal.
- **GPIO 0, 12 dihindari** karena strapping pin yang riskan: keadaannya saat
  boot menentukan mode boot atau tegangan flash.
- **GPIO 15 dipakai untuk IN1** meski juga strapping pin (menentukan
  verbosity log boot). Ini aman karena motor tidak mungkin berputar selama
  `ENA` masih rendah di awal boot — keadaan `IN1` saat itu tidak berpengaruh
  ke apa pun. **Jangan** pindahkan `ENA` sendiri ke pin strapping manapun:
  `ENA` yang salah keadaan saat boot berarti duty motor tidak tentu.

Semuanya ada di `firmware/rc_car_esp32/config.h` kalau perlu diubah.

---

## 4. L298N

### Dua jumper yang wajib dilepas

**Jumper ENA** (dan ENB). Kalau dibiarkan terpasang, ENA terikat ke 5 V dan
motor hanya punya dua keadaan: mati atau kencang penuh. Sinyal PWM dari
GPIO 25 tidak akan berpengaruh sama sekali.

**Jumper 5 V regulator.** Melepasnya mematikan regulator on-board 78M05,
karena kita tidak mau regulator itu yang menanggung beban servo dan kedua
ESP32 (lihat bagian 2). **Tapi pin `5V` di header L298N BUKAN cuma
keluaran regulator itu — ia juga jalur masuk daya logika untuk chip L298N
sendiri.** Chip L298N butuh dua daya terpisah: `Vs` untuk mendorong motor,
dan suplai logika (yang membaca sinyal `IN1`/`IN2`/`ENA`) lewat pin `5V`
ini. Cabut jumpernya, tapi **pin `5V` WAJIB tetap disambung** — ke rel 5 V
yang sama dengan servo (keluaran step-down #2), bukan dibiarkan
mengambang. Kalau dibiarkan mengambang, chip L298N sama sekali tidak
mendapat daya logika dan H-bridge tidak akan pernah aktif — gejalanya
motor benar-benar diam tanpa getaran sekalipun sinyal dari ESP32 sudah
benar.

### Sambungan

| Terminal L298N | Menuju |
|---|---|
| `Vs` (12 V in) | keluaran step-down #1 |
| `GND` | star ground |
| `5V` | **step-down #2 (rel 5 V yang sama dengan servo) — WAJIB, bukan mengambang** |
| `ENA` | ESP32 GPIO 4 |
| `IN1` | ESP32 GPIO 15 |
| `IN2` | ESP32 GPIO 22 |
| `OUT1` | motor belakang, kabel 1 |
| `OUT2` | motor belakang, kabel 2 |

Kalau arah maju/mundur terbalik, tukar `OUT1` dengan `OUT2`. Jangan
membalikkannya lewat program — perilaku rem dan jeda balik arah dihitung
berdasarkan asumsi kabel yang benar.

### Resistor pulldown — wajib, bukan opsional

Pasang **resistor pulldown 10 kΩ** dari `ENA`, `IN1`, dan `IN2` masing-masing
ke `GND`, sedekat mungkin dengan pin ESP32. Pin ESP32 mengambang selama reset
dan boot, dan `ENA` yang mengambang membuat keadaan motor tidak tentu selama
jendela waktu itu — bisa jadi PWM acak, bisa jadi seolah full duty, tergantung
noise sesaat. Pulldown memastikan ketiga pin itu diam di LOW sampai firmware
benar-benar mengambil alih dan menuliskan nilai yang pasti.

### Peredam noise motor

Motor DC bersikat menghasilkan percikan listrik yang mengganggu WiFi dan
membuat garis di video. Pasang tiga kapasitor keramik 100 nF langsung di
badan motor:

```
   terminal A ---+---[100nF]---+--- terminal B
                 |             |
             [100nF]       [100nF]
                 |             |
                 +----casing---+
```

Jauhkan juga kabel motor dari modul kamera dan antenanya.

---

## 5. Servo digital

| Kabel servo | Warna umum | Menuju |
|---|---|---|
| Sinyal | oranye / putih / kuning | ESP32 GPIO 13 |
| Positif | merah | 5 V dari step-down #2 (+ elko 1000 µF di sini) |
| Negatif | coklat / hitam | star ground |

**Jangan** memberi daya servo dari pin 5 V ESP32. Jalur pada board ESP32
tidak dirancang untuk arus servo, dan lonjakannya akan me-reset ESP32.

### Menyetel batas mekanis

`SERVO_MIN_US` dan `SERVO_MAX_US` di `config.h` adalah pengaman linkage
terakhir. Cara menyetelnya:

1. Mulai dari nilai sempit: `SERVO_MIN_US 1300`, `SERVO_MAX_US 1700`.
2. Flash, lalu putar stir pelan sampai mentok kiri dan kanan.
3. Lebarkan **50 µs setiap kali**, flash ulang, dan dengarkan.
4. Begitu servo mulai mendengung menahan di ujung, Anda sudah kelewatan.
   Mundur 50 µs dan berhenti di situ.

Servo yang terus menahan di ujung mekanisnya akan panas dan rusak dalam
hitungan menit. Suara dengung adalah satu-satunya peringatan yang Anda dapat.

`SERVO_FREQ_HZ` boleh dinaikkan dari 50 ke 200 Hz kalau datasheet servo Anda
mengizinkan — responsnya terasa jauh lebih tajam. Servo analog akan rusak
pada frekuensi setinggi itu, jadi pastikan dulu.

---

## 6. Pembagi tegangan baterai

```
   B+ (4S) ----[ R1 = 100k ]----+----[ R2 = 22k ]---- GND
                                |
                                +---- GPIO 34
                                |
                             [100nF]
                                |
                               GND
```

Pada 16,8 V (4S penuh), tegangan di GPIO 34 = 16,8 × 22/122 = **3,03 V**,
aman di bawah batas 3,3 V ADC.

Kapasitor 100 nF meredam noise motor agar pembacaan tidak melompat-lompat.

### Kalibrasi — jangan dilewati

1. Ukur tegangan baterai sungguhan dengan multimeter.
2. Baca angka tegangan di HUD (atau di Serial Monitor).
3. Sesuaikan `VBAT_DIVIDER_RATIO` di `config.h`:

   ```
   rasio_baru = rasio_lama × (tegangan_multimeter / tegangan_terbaca)
   ```

Resistor toleransi 5% membuat pembacaan meleset sampai 0,8 V pada 4S. Itu
cukup untuk membuat peringatan baterai jadi tidak berguna — bisa terlambat
memperingatkan, yang berarti sel rusak.

---

## 7. Modul kamera

Proyek ini memakai **Seeed Studio XIAO ESP32S3 Sense**. Sub-bagian AI-Thinker
di bawah dipertahankan karena `firmware/rc_cam_esp32` masih mendukungnya
sebagai modul cadangan (lihat `CAM_BOARD_XIAO_S3` di `camera_pins.h`), tapi
modul yang sebenarnya dipakai dan dirakit adalah XIAO.

### 7a. Seeed XIAO ESP32S3 Sense

#### Daya

XIAO ESP32S3 Sense punya dua pin daya di header-nya: `5V` dan `3V3`.

- **`5V`** adalah keluaran 5 V dari port USB-C sekaligus bisa dipakai sebagai
  **input** — inilah pin yang kita pakai, disambung ke step-down #2 seperti
  modul kamera sebelumnya. Regulator onboard modul yang menurunkannya ke
  3,3 V untuk chip dan sensor kamera.
- **`3V3`** adalah keluaran regulator onboard (maks. ~700 mA) — jangan
  disuntik dari luar; pakai hanya kalau Anda perlu menyadap 3,3 V untuk
  sensor tambahan.

| Pin XIAO ESP32S3 Sense | Menuju |
|---|---|
| `5V` | step-down #2, dengan elko **470 µF** + keramik 100 nF sedekat mungkin |
| `GND` | star ground |

Elko itu bukan pilihan. Brownout saat WiFi transmit adalah penyebab nomor
satu modul kamera ESP32 yang boot-loop — sama berlakunya di chip S3 seperti
di ESP32 biasa.

Firmware ini **sengaja tidak mematikan brownout detector**. Banyak contoh di
internet melakukannya agar modul berhenti reboot, tapi itu hanya menyembunyikan
tegangan yang memang kurang sambil membiarkan chip berjalan di luar batas
amannya. Kalau modul Anda reboot, perbaiki dayanya.

#### Cara flash

Jauh lebih sederhana dibanding AI-Thinker: modul ini punya **USB-C
bawaan**, jadi **tidak perlu adapter FTDI** dan **tidak perlu jumper
GPIO0-GND**.

1. Sambungkan XIAO ke laptop lewat kabel USB-C (kabel data, bukan
   kabel charge-only).
2. Di Arduino IDE pilih board **XIAO_ESP32S3**, Partition Scheme
   **Default with spiffs (3MB APP/1.5MB SPIFFS)**, dan PSRAM **OPI PSRAM**
   (modul ini punya PSRAM 8 MB lewat OPI — kalau opsi PSRAM dibiarkan
   "Disabled", kamera akan menolak resolusi di atas QVGA).
3. Pilih port serial yang muncul, lalu Upload. Tidak ada langkah
   sebelum/sesudah upload yang perlu dilakukan manual.

Kalau board **tidak terdeteksi** (port tidak muncul di Arduino IDE, atau
upload gagal langsung di awal), masuk mode bootloader manual — prosedur
resmi dari Seeed:

1. Tahan tombol **BOOT** tanpa dilepas.
2. Sambungkan kabel USB-C ke komputer sambil BOOT masih ditahan (atau, kalau
   kabel sudah tersambung, tekan **RESET** sekali sambil BOOT masih
   ditahan).
3. Lepas tombol BOOT setelah komputer mendeteksi port modul.
4. Upload seperti biasa. Modul akan boot normal setelah upload selesai.

### 7b. AI-Thinker ESP32-CAM (cadangan)

#### Daya

| Pin ESP32-CAM | Menuju |
|---|---|
| `5V` | step-down #2, dengan elko **470 µF** + keramik 100 nF sedekat mungkin |
| `GND` | star ground |

Sama seperti XIAO: elko itu bukan pilihan, dan brownout detector di
firmware **sengaja tidak dimatikan** — kalau modul reboot saat transmit,
perbaiki dayanya, bukan kode-nya.

#### Cara flash

Modul ini tidak punya port USB, jadi butuh adapter USB-serial.

| Adapter FTDI/CH340 | ESP32-CAM |
|---|---|
| `5V` | `5V` |
| `GND` | `GND` |
| `TX` | `U0R` (RX) |
| `RX` | `U0T` (TX) |

Set jumper adapter ke **logic 3,3 V**. Beberapa adapter 5 V memang bisa,
tetapi tidak dijamin dan bisa merusak pin.

Langkahnya:

1. Sambungkan **GPIO 0 ke GND** dengan kabel jumper.
2. Tekan tombol `RST` di modul.
3. Di Arduino IDE pilih board **AI Thinker ESP32-CAM**, dan
   Partition Scheme **Huge APP (3MB No OTA/1MB SPIFFS)**.
4. Upload.
5. **Lepas kabel GPIO 0 – GND.**
6. Tekan `RST` sekali lagi. Modul akan boot normal.

Kalau lupa langkah 5, modul akan tetap di mode flash dan tidak menjalankan
program apa pun.

Kalau berpindah antara XIAO dan AI-Thinker, ingat ubah `CAM_BOARD_XIAO_S3`
di `firmware/rc_cam_esp32/camera_pins.h` sesuai modul yang sedang dipakai,
selain mengubah board/opsi di Arduino IDE.

---

## 8. Checklist perakitan

Kerjakan berurutan. Setiap tahap punya cara memastikan hasilnya benar
sebelum lanjut.

**Sebelum menyambung apa pun ke baterai**

- [ ] Setel step-down #1 ke **12,0 V** dengan multimeter, tanpa beban
- [ ] Setel step-down #2 ke **5,0 V** dengan multimeter, tanpa beban
- [ ] Lepas jumper **ENA** di L298N
- [ ] Lepas jumper **5 V** di L298N
- [ ] Rakit pembagi tegangan dan ukur keluarannya (harus ~3,0 V saat 4S penuh)

**Perakitan**

- [ ] Satukan semua GND ke satu titik dekat terminal negatif baterai
- [ ] Pasang elko: 470 µF di Vs L298N, 1000 µF di 5 V servo, 470 µF di modul kamera
- [ ] Pasang tiga keramik 100 nF di badan motor
- [ ] Sambungkan sinyal: GPIO 4/15/22 ke ENA/IN1/IN2, GPIO 13 ke servo
- [ ] Pasang resistor pulldown 10 kΩ dari ENA, IN1, dan IN2 masing-masing
      ke GND (pin ESP32 mengambang saat reset/boot; ENA yang mengambang
      membuat keadaan motor tidak tentu)
- [ ] Jauhkan kabel motor dari modul kamera dan antenanya

**Sebelum menyalakan pertama kali**

- [ ] Isi `WIFI_SSID` dan `WIFI_PASS` di **kedua** firmware
- [ ] **Angkat mobil di atas balok** sehingga roda tidak menyentuh lantai
- [ ] Set `max_forward: 0.3` di `ground/config.yaml`
- [ ] Siapkan cara memutus baterai dengan cepat

**Urutan menyalakan**

1. Nyalakan hotspot WiFi di LattePanda **lebih dulu**
2. Baru sambungkan baterai mobil
3. Tunggu LED ESP32 berubah dari kedip cepat ke kedip lambat (WiFi tersambung)
4. Jalankan `python main.py`

Urutan ini penting: kalau mobil menyala sebelum hotspot ada, ia akan
menghabiskan waktu mencoba menyambung ulang.

---

## 9. Masalah umum

| Gejala | Kemungkinan penyebab | Tindakan |
|---|---|---|
| Modul kamera reboot tiap servo bergerak | Rel 5 V drop | Elko 1000 µF di servo; pisahkan rel ESP32 |
| Motor hanya bisa mati / penuh | Jumper ENA masih terpasang | Lepas jumper ENA |
| Motor tidak berputar sama sekali | Level logic 3,3 V kurang untuk L298N | Naikkan `MOTOR_MIN_DUTY`; kalau tetap, pasang level shifter |
| Motor mendengung tapi diam | Duty terlalu rendah | Naikkan `MOTOR_MIN_DUTY` di `config.h` |
| Servo bergetar sendiri | Ground tidak menyatu, atau noise motor | Periksa star ground; tambah keramik di motor |
| Servo mendengung di ujung | `SERVO_MIN/MAX_US` terlalu lebar | Persempit 50 µs |
| Arah maju/mundur terbalik | Kabel motor tertukar | Tukar OUT1 dan OUT2 |
| Arah belok terbalik | Arah servo | Set `invert: true` di `ground/config.yaml` |
| Video penuh garis | Noise motor | Keramik di motor; jauhkan kabel |
| Ping melonjak acak ratusan ms | Power save WiFi | Pastikan `WiFi.setSleep(false)` ada di kedua firmware |
| Tegangan HUD tidak cocok multimeter | Toleransi resistor | Kalibrasi `VBAT_DIVIDER_RATIO`, bagian 6 |
| Mobil tidak ditemukan | Subnet berbeda | Cocokkan `CAR_IP` dengan subnet hotspot, atau set `USE_DHCP 1` |
