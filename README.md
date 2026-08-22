# RC Car FPV — ESP32 + Stir PXN V9

Mobil RC yang dikendarai dengan stir dan pedal sungguhan sambil melihat video
dari kamera di mobil.

```
        DARAT                                    MOBIL
  +------------------+                   +---------------------+
  | Stir PXN V9      |--USB--+           | ESP32 dev module    |
  | + pedal gas/rem  |       |           |  |- L298N -> motor  |
  +------------------+       v           |  |    (OUT1/OUT2)   |
                     +---------------+   |  +- servo digital   |
                     |  LattePanda   |   +---------------------+
                     |  Python app   |<--- UDP 50 Hz ---+
                     |  HUD + video  |
                     +---------------+<-- HTTP MJPEG --+-------------+
                             |                         | XIAO ESP32S3|
                             +--- Hotspot WiFi --------+-------------+
```

- **LattePanda** membaca stir, menerapkan kurva gas dan trim, lalu mengirim
  perintah 50 kali per detik.
- **ESP32 dev module** menggerakkan motor belakang lewat L298N dan servo
  kemudi, dan mengirim balik telemetri.
- **XIAO ESP32S3 Sense** melayani video secara terpisah, supaya beban video
  tidak pernah mengganggu latensi kendali.

Kurva gas, deadzone, trim servo, dan batas kecepatan hidup di sisi darat —
semuanya bisa diubah tanpa flash ulang ESP32.

---

## Balapan dengan 3 mobil

Kalau Anda menyiapkan lebih dari satu mobil (3 mobil, 3 LattePanda, 1
router GL.iNet), baca [docs/balapan-3-unit.md](docs/balapan-3-unit.md) —
tabel alamat lengkap, langkah setup per unit, checklist hari balapan, dan
cara memastikan tidak ada cross-control antar mobil.

Ringkasnya: setiap mobil punya `UNIT_ID` (1/2/3) yang diset sekali di
firmware, dan setiap LattePanda punya `unit:` yang sama di
`ground/config.yaml`. Semua alamat IP diturunkan otomatis dari angka itu.

---

## Status pengujian terakhir

Checkpoint terbaru proyek, hasil kalibrasi PXN, perbaikan yang sudah masuk,
dan pekerjaan hardware yang belum dilakukan dicatat di
[docs/test-status.md](docs/test-status.md).

---

## Isi proyek

```
RC Car/
├── docs/
│   ├── wiring.md            Perakitan, skema daya, pinout, checklist
│   ├── protocol.md          Spesifikasi paket UDP (kontrak antar sisi)
│   └── balapan-3-unit.md    Setup 3 mobil/3 LattePanda, alamat, checklist
├── firmware/
│   ├── rc_car_esp32/  Otak mobil (ESP32 Dev Module)
│   └── rc_cam_esp32/  Kamera FPV (XIAO ESP32S3 Sense, AI-Thinker ESP32-CAM
│                       cadangan)
└── ground/
    ├── main.py        Aplikasi ground station
    ├── calibrate.py   Wizard kalibrasi stir
    ├── build_exe.py   Build RCCar.exe + Kalibrasi.exe (PyInstaller)
    ├── fake_car.py    Simulator mobil
    ├── fake_cam.py    Simulator kamera
    └── config.yaml    Semua tuning (termasuk `unit:` mobil mana yang dikendalikan)
```

---

## Mulai dari sini: coba tanpa hardware

Seluruh aplikasi darat bisa dijalankan penuh sebelum satu kabel pun
disambungkan. Lakukan ini dulu — jauh lebih mudah menemukan masalah di meja
daripada di lapangan dengan mobil yang sudah dirakit.

```bash
pip install -r ground/requirements.txt
```

Buka **tiga** terminal di folder `ground/`:

```bash
python fake_car.py
```

```bash
python fake_cam.py
```

```bash
python main.py --car 127.0.0.1 --cam http://127.0.0.1:8080/stream
```

Yang harus Anda lihat: jendela berisi pola uji bergerak, HUD di atasnya,
banner **DISARMED**, dan PING di bawah 5 ms.

Kalau stir belum terpasang, aplikasi otomatis memakai keyboard: panah
kiri/kanan untuk stir, panah atas/bawah untuk gas dan mundur.

### Cobalah failsafe sekarang juga

Tekan `SPASI` untuk arm, tahan panah atas, lalu **hentikan `fake_car.py`
dengan Ctrl+C**. Banner harus berubah merah menjadi FAILSAFE dalam waktu
kurang dari setengah detik.

Sekarang jalankan lagi `fake_car.py`. Perhatikan bahwa mobil **tidak** langsung
armed kembali — Anda harus menekan `SPASI` lagi secara sadar. Perilaku ini
disengaja dan merupakan pengaman terpenting di seluruh proyek; penjelasannya
ada di [docs/protocol.md](docs/protocol.md) bagian 5.

---

## Kalibrasi stir

PXN V9 punya saklar mode, dan nomor axis berubah mengikuti mode tersebut.
Karena itu jangan memakai angka hafalan dari tutorial mana pun — jalankan:

```bash
python calibrate.py
```

Wizard akan memandu: putar stir mentok kiri, mentok kanan, injak gas, injak
rem, lalu pilih tombol arm dan tombol stop darurat. Hasilnya disimpan ke
`calibration.yaml`.

Kalau Anda punya **dua unit PXN V9** yang tersambung bersamaan, wizard akan
meminta Anda memilih salah satu. Nama perangkat ikut disimpan, jadi pilihan
Anda tetap benar walaupun urutan USB berubah setelah restart.

Jalankan ulang `calibrate.py` setiap kali mengganti stir atau menggeser
saklar mode.

---

## Efek suara (SFX)

Ground station memutar suara mesin (mengikuti intensitas pedal gas mentah),
klakson, dan suara arm — semuanya diputar di laptop/LattePanda, bukan di
mobil, jadi tidak mempengaruhi perintah yang dikirim ke ESP32.

Ganti pack suara kapan saja saat aplikasi berjalan, tanpa perlu berhenti:

| Tombol | Ganti pack |
|---|---|
| `G` / `Shift+G` | gas — berikutnya / sebelumnya |
| `N` / `Shift+N` | klakson — berikutnya / sebelumnya |
| `M` / `Shift+M` | arm — berikutnya / sebelumnya |

Pilihan pack terakhir disimpan otomatis ke `config.yaml` (kunci `sfx:`) saat
aplikasi ditutup, jadi tidak perlu dipilih ulang tiap sesi. Untuk mematikan
semua suara tanpa menghapus berkasnya, set `sfx.enabled: false` di
`config.yaml`.

Klakson bisa dipicu dari tombol keyboard `H` (ditahan) atau dari tombol
fisik di stir. Tombol fisik untuk klakson dikalibrasi lewat `calibrate.py` —
langkah barunya muncul tepat setelah langkah kalibrasi tombol stop darurat,
dengan wizard yang sama seperti langkah arm/estop.

Berkas suara berasal dari Mixkit (mixkit.co), lisensi *Mixkit Free
License* — bebas dipakai personal maupun komersial dan tidak wajib
atribusi. Lihat `ground/assets/sfx/manifest.yaml` untuk daftar lengkap
judul dan sumbernya.

---

## Membuat .exe (LattePanda Windows)

Untuk dipakai di lapangan tanpa perlu menginstal Python di tiap LattePanda:

```bash
pip install pyinstaller
python build_exe.py
```

Menghasilkan `ground/dist/RCCarField/` berisi `RCCar.exe`, `Kalibrasi.exe`,
`config.yaml`, `calibration.yaml`, dan `BACA-DULU.txt` — salin seluruh
folder itu ke LattePanda. `config.yaml` dan `calibration.yaml` sengaja ada
DI LUAR exe supaya bisa diedit langsung di lapangan tanpa build ulang.

---

## Menyiapkan hardware

Baca [docs/wiring.md](docs/wiring.md) sampai selesai. Ringkasnya:

1. **Jangan ambil 5 V dari pin 5 V L298N.** Regulator di board itu hanya
   sanggup ~0,5 A, sedangkan servo saja bisa menarik 2,5 A saat menahan.
   Pakai step-down terpisah dari baterai.
2. Lepas **jumper ENA** dan **jumper 5 V** di L298N.
3. Satukan semua ground di satu titik.
4. Pasang elko 1000 µF di jalur 5 V servo dan 470 µF di modul kamera.

Lalu isi kredensial WiFi di kedua firmware:

- `firmware/rc_car_esp32/config.h` → `WIFI_SSID`, `WIFI_PASS`
- `firmware/rc_cam_esp32/rc_cam_esp32.ino` → `WIFI_SSID`, `WIFI_PASS`

Kalau Anda menyiapkan **lebih dari satu mobil**, `UNIT_ID` di kedua berkas
itu (baris paling atas, sangat jelas ditandai) adalah satu-satunya hal lain
yang perlu diubah per mobil — semua alamat IP diturunkan otomatis darinya.
Lihat [docs/balapan-3-unit.md](docs/balapan-3-unit.md).

> **Repo ini privat dan harus tetap privat.** Kredensial WiFi tertulis langsung di
> `firmware/rc_car_esp32/config.h` dan `firmware/rc_cam_esp32/rc_cam_esp32.ino`.
> Sebelum membuat repo ini publik atau membagikannya, ganti dulu kedua nilai itu
> menjadi placeholder dan bersihkan riwayat commit — menghapusnya di commit baru
> saja tidak cukup, nilainya tetap ada di riwayat.

### Flash

| Sketch | Board di Arduino IDE | Catatan |
|---|---|---|
| `rc_car_esp32` | ESP32 Dev Module | Colok USB biasa |
| `rc_cam_esp32` | XIAO_ESP32S3 (default) | Partition: Default with spiffs. PSRAM: OPI PSRAM. Colok USB-C biasa, tidak perlu adapter apa pun |
| `rc_cam_esp32` (cadangan) | AI Thinker ESP32-CAM | Ganti `CAM_BOARD_XIAO_S3` ke `0` di `camera_pins.h`. Partition: Huge APP. Butuh adapter FTDI dan GPIO0 ke GND saat upload |

Membutuhkan **ESP32 core 3.x** di Arduino IDE. Firmware ini memakai API LEDC
gaya baru (`ledcAttach`), bukan `ledcSetup()` yang dipakai tutorial lama.
Tidak ada library tambahan yang perlu dipasang.

---

## Menjalankan

Urutan menyalakan penting:

1. Nyalakan hotspot WiFi di LattePanda **lebih dulu**
2. Sambungkan baterai mobil
3. Tunggu LED ESP32 berubah dari kedip cepat ke kedip lambat
4. `python main.py`

### Arti LED di mobil

| LED | Arti |
|---|---|
| Kedip cepat | WiFi belum tersambung |
| Kedip lambat | Tersambung, **disarmed** — aman didekati |
| Kedip ganda | Failsafe, tautan putus |
| Nyala terus | **ARMED** — motor bisa bergerak kapan saja |

### Tombol

| Tombol | Fungsi |
|---|---|
| `SPASI` | arm / disarm |
| `E` | stop darurat |
| `[` `]` | geser trim stir kiri / kanan |
| `H` (tahan) | klakson |
| `G` / `Shift+G` | ganti pack suara gas berikutnya / sebelumnya |
| `N` / `Shift+N` | ganti pack suara klakson berikutnya / sebelumnya |
| `M` / `Shift+M` | ganti pack suara arm berikutnya / sebelumnya |
| `F5` | simpan trim ke `config.yaml` |
| `F11` | layar penuh |
| `ESC` | keluar |

Arm hanya bisa dilakukan kalau mobil sudah menjawab **dan** pedal gas dalam
keadaan netral.

---

## Menyetel rasa berkendara

Semuanya di `ground/config.yaml`, tidak perlu flash ulang.

| Setelan | Naikkan kalau... |
|---|---|
| `throttle.max_forward` | mobil terasa terlalu lambat (mulai dari **0.3**) |
| `throttle.expo` | gas terasa terlalu mendadak di awal pedal |
| `throttle.slew_rate` | mobil terasa lambat menanggapi (hati-hati: menaikkan lonjakan arus) |
| `steering.expo` | mobil terlalu sensitif di sekitar lurus |
| `steering.deadzone` | roda bergerak sendiri padahal stir diam |
| `steering.max_angle` | turunkan kalau belokan terlalu tajam sampai mudah terguling |

Untuk trim: sambil mengemudi, tekan `[` atau `]` sampai mobil berjalan lurus,
lalu tekan `F5` untuk menyimpannya.

---

## Sebelum menurunkan mobil ke lantai

Kerjakan berurutan dengan **roda di udara**:

1. Sisi darat lulus uji dengan `fake_car.py` — termasuk uji failsafe di atas
2. Serial Monitor mobil menunjukkan WiFi tersambung dan paket masuk
3. Servo bergerak halus, tidak mendengung di ujung
4. Motor maju, netral, mundur dengan `max_forward: 0.3`
5. L298N dan step-down hanya hangat setelah 30 detik, tidak panas
6. **Uji failsafe di hardware:** dengan motor berputar, matikan hotspot.
   Motor harus berhenti dalam 300 ms. Ini uji paling penting dari semuanya.
7. Video mengalir dan modul kamera tidak reboot saat servo bergerak
8. Ping di HUD di bawah 30 ms

Baru setelah semuanya lolos: turunkan ke lantai, di ruang terbuka, mulai dari
`max_forward: 0.3`.

---

## Kalau ada yang tidak beres

Tabel gejala dan penyebab ada di [docs/wiring.md](docs/wiring.md) bagian 9.
Tiga yang paling sering:

- **Modul kamera reboot saat stir diputar** → rel 5 V drop. Ini soal daya, bukan
  program. Lihat bagian 2 di wiring.md.
- **Motor hanya mati atau kencang penuh** → jumper ENA di L298N belum dilepas.
- **Ping melonjak acak** → power save WiFi. Pastikan `WiFi.setSleep(false)`
  masih ada di kedua firmware.

---

## Batasan yang perlu diketahui

Beberapa hal ditentukan oleh komponen, bukan oleh program:

- **Waktu jalan 5–8 menit** dengan 4S 850 mAh. Perlu baterai lebih besar
  kalau ingin lebih lama.
- **L298N menjatuhkan 2–2,5 V.** Dari 12 V, motor menerima sekitar 10 V.
  Kalau butuh efisiensi lebih, driver MOSFET seperti BTS7960 adalah
  penggantinya.
- **L298N tidak punya proteksi arus.** Motor di atas ~2 A kontinu akan
  membuatnya terlalu panas.
- **Jangkauan WiFi** biasanya 30–50 m di lapangan terbuka, tergantung antena
  dan hotspot. Failsafe akan bekerja begitu tautan putus, tetapi mobil akan
  berhenti di tempat — bukan kembali sendiri.
