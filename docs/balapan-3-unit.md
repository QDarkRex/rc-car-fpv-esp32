# Balapan 3 mobil, 3 LattePanda

Panduan ini untuk konfigurasi balapan: **3 mobil**, **1 router GL.iNet**
(subnet `192.168.8.x`, gateway `.1`), dan **3 LattePanda Windows** — satu
LattePanda per mobil, masing-masing dengan stir PXN sendiri.

Latar belakang teknisnya (kenapa `unit_id` perlu ditambahkan ke protokol,
dan kenapa itu membuat discovery broadcast tetap aman dipakai bersama)
ada di [protocol.md](protocol.md) bagian 7. Dokumen ini murni langkah
praktis di lapangan.

---

## 1. Tabel alamat

| Unit | IP mobil (ESP32 dev module) | IP kamera (XIAO ESP32S3) |
|---|---|---|
| 1 | 192.168.8.50 | 192.168.8.60 |
| 2 | 192.168.8.51 | 192.168.8.61 |
| 3 | 192.168.8.52 | 192.168.8.62 |

Router GL.iNet: gateway `192.168.8.1`, DHCP otomatis `192.168.8.100` sampai
`192.168.8.249`. Rentang IP mobil/kamera (`.50`-`.52` dan `.60`-`.62`)
sengaja di luar rentang DHCP itu, jadi tidak akan pernah bentrok dengan
perangkat lain yang minta IP otomatis (laptop, HP, dll).

Semua alamat di atas **diturunkan otomatis** dari satu angka `UNIT_ID` /
`unit:` — tidak perlu diketik satu-satu di banyak tempat. Lihat bagian 2.

---

## 2. Menyiapkan satu unit (ulangi untuk unit 1, 2, dan 3)

### a. Firmware mobil

1. Buka `firmware/rc_car_esp32/config.h`.
2. Ubah **satu baris** di paling atas: `#define UNIT_ID 1` menjadi `2` atau
   `3` sesuai mobil yang sedang di-flash.
3. Isi/periksa `WIFI_SSID` dan `WIFI_PASS` (sama untuk ketiga mobil, sesuai
   SSID hotspot GL.iNet).
4. Flash ke ESP32 Dev Module (FQBN `esp32:esp32:esp32`).
5. Buka Serial Monitor, pastikan baris `[LINK] tersambung, IP ...`
   menunjukkan IP yang benar sesuai tabel di bagian 1 (mis. unit 2 harus
   menunjukkan `192.168.8.51`).

### b. Firmware kamera

1. Buka `firmware/rc_cam_esp32/rc_cam_esp32.ino`.
2. Ubah `#define UNIT_ID 1` ke angka yang **SAMA** dengan mobil yang baru
   di-flash di langkah (a). Ini WAJIB sama — kamera dan mobil unit yang
   sama harus punya UNIT_ID identik.
3. Flash ke XIAO ESP32S3 Sense (FQBN
   `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`, PSRAM: OPI PSRAM).
4. Buka Serial Monitor, pastikan `Stream di http://192.168.8.6X/stream`
   menunjukkan IP yang benar.

### c. Aplikasi darat (LattePanda)

1. Salin folder hasil build (`ground/dist/RCCarField/`, lihat bagian 5 di
   README.md dan `ground/build_exe.py`) ke LattePanda unit ini.
2. Buka `config.yaml` di folder itu dengan Notepad.
3. Ubah baris `unit: 1` menjadi `2` atau `3`, **SAMA** dengan UNIT_ID mobil
   dan kamera unit ini. `network.car_ip` dan `camera.stream_url` TIDAK
   perlu disentuh — keduanya diturunkan otomatis dari `unit:` (lihat
   komentar di config.yaml untuk cara override manual kalau perlu).
4. Colok stir PXN V9 milik LattePanda ini, jalankan `Kalibrasi.exe`, ikuti
   wizard-nya sampai selesai. **Wajib diulang per LattePanda** — kalibrasi
   tidak portable antar unit stir yang berbeda.
5. Jalankan `RCCar.exe`, pastikan pojok kiri atas HUD menunjukkan
   **"UNIT N"** yang sesuai dengan mobil di depan Anda.

---

## 3. Checklist hari balapan

Per unit, sebelum mobil turun ke lintasan:

- [ ] Hotspot GL.iNet menyala **lebih dulu** dari mobil dan kamera.
- [ ] LED ESP32 mobil: kedip lambat (tersambung WiFi, disarmed).
- [ ] Serial Monitor / konsol mobil: `status` menunjukkan `unit ID mobil`
      yang benar dan `bukan-untuk-unit-ini` tidak melonjak liar (lihat
      bagian 5 di bawah).
- [ ] `RCCar.exe` di LattePanda: HUD menunjukkan **UNIT N** yang benar,
      banner berubah dari merah (mencari) ke "Mobil ditemukan".
- [ ] Video FPV mengalir, ping di HUD wajar (< 30 ms di lokasi).
- [ ] Tekan SPASI, pastikan mobil ARMED dan motor merespons — LALU DISARM
      lagi sebelum berangkat ke garis start kalau belum waktunya jalan.
- [ ] Uji failsafe sekali: motor berputar, matikan hotspot sebentar, motor
      harus berhenti (kalau `FAILSAFE_ENABLED` dinyalakan — lihat config.h;
      default proyek ini MEMATIKANNYA, lihat catatan di config.h).

Sebelum start bersamaan (ketiga mobil):

- [ ] Ketiga `unit:` di tiga LattePanda berbeda (1, 2, 3) — TIDAK ada yang
      sama.
- [ ] Ketiga `UNIT_ID` di firmware mobil dan kamera sudah dicocokkan
      dengan LattePanda yang mengendalikannya.
- [ ] Sempat coba gerakkan tiap mobil satu-satu dari LattePanda masing-
      masing, dan **amati mobil mana yang benar-benar bergerak** — ini
      cara paling langsung memastikan tidak ada cross-control sebelum
      ketiganya jalan bersamaan.

---

## 4. Bandwidth video: VGA vs QVGA

Diatur lewat satu baris `CAM_FRAMESIZE` di
`firmware/rc_cam_esp32/rc_cam_esp32.ino` (dekat baris ini ada blok komentar
mencolok dengan penjelasan yang sama seperti di bawah).

| Resolusi | Per kamera | 3 kamera bersamaan | Catatan |
|---|---|---|---|
| VGA (640x480), **dipakai sekarang** | ~3,5-5 Mbps | ~10-15 Mbps | Berisiko di 2,4 GHz kalau ketiga mobil balapan bersamaan — video atau kendali bisa tersendat |
| QVGA (320x240) | ~1,5 Mbps | ~4,5 Mbps | Aman, menyisakan banyak ruang untuk paket kendali 50 Hz |

**Kalau 3 stream video ternyata membuat jaringan tersendat saat latihan**,
turunkan ke QVGA:

1. Buka `rc_cam_esp32.ino`, ubah `#define CAM_FRAMESIZE FRAMESIZE_VGA`
   menjadi `FRAMESIZE_QVGA`.
2. Flash ulang **ketiga** modul kamera — bukan cuma satu, supaya beban
   bandwidth turun serentak di ketiga mobil. Kalau cuma sebagian yang
   diturunkan, sisanya tetap membebani jaringan yang sama dan masalahnya
   tidak hilang.

---

## 5. Memastikan tidak ada cross-control

Protokol v3 menambahkan `unit_id` ke setiap paket kontrol dan telemetri
(lihat [protocol.md](protocol.md) bagian 7). Dua tempat untuk memeriksa
tidak ada mobil yang salah kunci:

**Di mobil**, lewat konsol serial (kabel USB, Serial Monitor 115200 baud),
ketik `status`:

```
paket masuk   : rx 1502  rusak 0  basi 3  bukan-untuk-unit-ini 0
unit ID mobil : 1
```

`bukan-untuk-unit-ini` naik berarti mobil ini MENDENGAR paket kontrol dari
ground station lain (unit lain), tapi membuangnya — ini **normal** kalau
ground station lain memang aktif di jaringan yang sama, dan justru
membuktikan penyaringan bekerja. Yang harus diwaspadai adalah `rx` yang
naik padahal ground station Anda sendiri belum mengirim apa-apa — itu
tandanya UNIT_ID mobil ini kebetulan sama dengan mobil lain.

**Di ground station**, `Link.foreign_count` (lihat
`ground/rcground/link.py`) menghitung telemetri sehat yang dibuang karena
`unit_id`-nya bukan milik ground station itu. Ini tidak ditampilkan di HUD
secara default (HUD sudah padat), tapi bisa diperiksa lewat mode uji atau
ditambahkan ke HUD kalau ingin selalu terlihat.

Cara paling meyakinkan tetap **uji fisik**: gerakkan tiap mobil satu-satu
dari LattePanda masing-masing sebelum balapan dimulai, dan pastikan hanya
mobil yang dimaksud yang bergerak (lihat checklist bagian 3).
