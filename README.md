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
│   ├── rc_car_esp32/     Otak mobil (ESP32 Dev Module)
│   ├── rc_cam_esp32/     Kamera FPV (XIAO ESP32S3 Sense, AI-Thinker
│   │                     ESP32-CAM cadangan) — kamera jadi KLIEN router
│   └── rc_cam_esp32_ap/  Varian kamera sebagai ACCESS POINT sendiri.
│                         Untuk mengatasi video patah-patah — lihat
│                         "Kalau video terasa telat" di bawah.
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

### Kalibrasi titik servo

Untuk menyesuaikan output servo kiri/tengah/kanan tanpa mengubah firmware,
jalankan:

```bash
python calibrate.py --servo
```

Wizard ini mengirim paket `SERVO_CALIBRATION` yang tetap disarmed dengan gas
dan rem nol, sehingga servo dapat bergerak tanpa mengaktifkan motor. Pilih `L`,
`C`, atau `R`, atur output dengan tombol panah sambil melihat servo, lalu tekan
ENTER untuk menyimpan. `ESC`, error, atau penutupan jendela selalu mengirim
beberapa paket center/netral. Nilai disimpan di blok `steering:` pada
`config.yaml`; default `-1.0 / 0.0 / 1.0` mempertahankan perilaku lama.

**Mode stir langsung (W).** Kalau stir PXN V9 sudah dikalibrasi lewat
`python calibrate.py` (biasa, tanpa `--servo`) dan masih tersambung, tekan
`W` untuk beralih ke mode ini: servo mobil bergerak *real-time* mengikuti
putaran stir sungguhan, memakai titik `L/C/R` yang sedang Anda atur. Putar
stir mentok kiri sambil menahan, lalu atur nilai `LEFT` dengan panah sampai
roda mobil benar-benar mentok kiri secara fisik — begitu juga untuk tengah
dan kanan. Ini menyinkronkan program, stir, dan servo mobil dalam satu
langkah, alih-alih menebak angka lewat tombol panah tanpa umpan balik. Tekan
`W` lagi untuk kembali ke mode manual. Kalau stir belum terdeteksi atau
belum pernah dikalibrasi, mode ini otomatis tidak ditawarkan dan wizard
tetap berjalan manual seperti biasa.

Uji tanpa mobil fisik dengan dua terminal dari folder `ground/`:

```bash
python fake_car.py
python calibrate.py --servo --car 127.0.0.1
```

---

## Efek suara (SFX)

Ground station memutar suara mesin (ignition, idle, lalu crossfade rev yang
mengikuti intensitas pedal gas), klakson, dan suara arm — semuanya diputar di
laptop/LattePanda, bukan di mobil, jadi tidak mempengaruhi perintah yang
dikirim ke ESP32.

Pack gas default adalah profil **Sportscar CC0**: enam loop WAV bertingkat
pitch dari OpenGameArt, dipakai sebagai layer RPM yang bersebelahan. Sumbernya
adalah [racing car engine sound loops](https://opengameart.org/content/racing-car-engine-sound-loops),
oleh domasx2, berlisensi CC0. Tidak ada aset Need for Speed atau aset game
berhak cipta yang digunakan. Metadata dan durasi tiap file tercatat di
`ground/assets/sfx/manifest.yaml`.

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

Klakson mengikuti selama tombol keyboard `H` atau tombol fisik di stir ditahan,
lalu berhenti saat dilepas. Tombol fisik untuk
klakson dikalibrasi lewat `calibrate.py` — langkah barunya muncul tepat
setelah langkah kalibrasi tombol stop darurat, dengan wizard yang sama
seperti langkah arm/estop.

Untuk menguji audio tanpa stir, jaringan, kamera, atau RC car, jalankan dari
folder `ground/`:

```bash
python sfx_demo.py
```

Gunakan `--silent` jika komputer tidak memiliki perangkat audio. Pengujian
state otomatis yang tidak membutuhkan speaker dijalankan dengan:

```bash
python -m unittest discover -s . -p "test_*.py"
```

Berkas suara berasal dari dua sumber, lisensinya beda per kategori — lihat
`ground/assets/sfx/manifest.yaml` untuk daftar lengkap judul dan sumbernya:

- **klakson & arm**: Mixkit (mixkit.co), lisensi *Mixkit Free License* —
  bebas dipakai personal maupun komersial, tidak wajib atribusi.
- **gas**: Freesound.org, campuran CC0 dan **CC BY 4.0** (wajib atribusi).
  Kredit untuk berkas CC BY 4.0: EvanBoyerman ("Sports car accelerating"
  medium & fast), jimmygu3 ("V8 Lotus sports car engine revs"),
  jerry.berumen ("Land Rover sport V6 revving"), zagi2 ("Rev up loop"),
  Debsound ("Rally car idle loop") — seluruhnya dari Freesound.org.

---

## Menjalankan langsung dari git (tanpa .exe)

Cocok untuk LattePanda yang sering di-update (tinggal `git pull`, tidak perlu
build ulang tiap kali kode berubah) atau kalau tidak ada media untuk
menyalin folder `dist/` (flashdisk, dll).

```bash
git clone https://github.com/QDarkRex/rc-car-fpv-esp32.git
cd rc-car-fpv-esp32/ground
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

Lalu edit `config.yaml` yang baru disalin: ubah `unit:` sesuai mobil yang
dikendalikan LattePanda ini (lihat [Kalibrasi stir](#kalibrasi-stir) di atas
untuk langkah kalibrasi, dan bagian [Balapan dengan 3
mobil](#balapan-dengan-3-mobil) untuk skema unit 1/2/3).

`config.yaml` dan `calibration.yaml` sengaja **TIDAK** ikut ter-*track* git
(lihat `.gitignore`) — keduanya murni pengaturan per-mesin (nomor unit,
kalibrasi stir fisik). Kalau ikut ter-*track*, `git pull` berikutnya akan
bentrok dengan perubahan lokal Anda. Jalankan `python calibrate.py` sekali
untuk membuat `calibration.yaml` sendiri, lalu jalankan dengan:

```bash
python main.py
```

Update berikutnya cukup `git pull` dari folder ini, tanpa menyentuh
`config.yaml`/`calibration.yaml` milik mesin ini sama sekali.

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

## Kalau video terasa telat

Jalur video sudah dirancang agar tidak pernah menumpuk frame lama: kamera
membuang frame yang belum sempat terkirim (`CAMERA_GRAB_LATEST`), sisi darat
hanya menyimpan satu frame terbaru, dan dekode JPEG dikerjakan di thread
video — bukan di loop kendali 50 Hz, supaya frame yang berat tidak pernah
menunda paket kendali.

Kalau masih terasa telat, urutan yang paling berpengaruh:

| Langkah | Di mana | Efek |
|---|---|---|
| Turunkan ke `FRAMESIZE_QVGA` | `firmware/rc_cam_esp32` → `CAM_FRAMESIZE` | Paling besar. ~1,5 Mbps/kamera, bukan ~4 Mbps |
| Naikkan `CAM_JPEG_QUALITY` (angka lebih besar = file lebih kecil) | firmware kamera | Frame lebih ringan, lebih tahan sinyal lemah |
| `display.smooth_scale: false` | `ground/config.yaml` | Hemat beberapa ms/frame di CPU lemah |
| Turunkan `display.hud_rate_hz` | `ground/config.yaml` | Mengembalikan CPU ke loop kendali; **tidak** menambah latensi video |
| Dekatkan antena / kurangi jumlah kamera aktif | lapangan | Rebutan 2,4 GHz adalah penyebab paling sering |

Bandingkan angka **VIDEO fps** di HUD dengan fps yang dicetak kamera di
Serial Monitor. Kalau HUD jauh lebih rendah, hambatannya di sisi darat
(CPU) — pakai dua baris `display:` di atas. Kalau keduanya sama-sama rendah,
hambatannya di kamera atau jaringan — pakai dua baris firmware di atas.

### Patah-patah ≠ latensi

Keduanya masalah berbeda dengan sebab berbeda, dan **VIDEO fps tidak bisa
membedakannya** karena ia rata-rata: beku 400 ms lalu menyusul beruntun
tetap terbaca ~20 fps. Untuk itu ada baris **PATAH** di HUD — jeda
terpanjang antar frame dalam 3 detik terakhir. Di bawah 120 ms gerakan
masih terbaca menerus; di atas 250 ms terasa jelas tersendat.

Penyebab paling lazim bukan kamera yang lambat, melainkan **kehilangan
paket**: video mengalir lewat TCP, dan satu segmen hilang menahan seluruh
aliran sampai kiriman ulangnya sampai. Video membeku, lalu frame menumpuk
datang serentak. Kalau `ping` ke mobil atau kamera menunjukkan RTO
sesekali, itu konfirmasinya.

Tiga penangkalnya, dari yang paling murah:

1. **Pindahkan kanal router** ke 1/6/11 yang paling lengang. Gratis, tanpa
   flash apa pun, dan sering paling berpengaruh.
2. **Perkecil frame** (`FRAMESIZE_QVGA`, naikkan `CAM_JPEG_QUALITY`).
   Frame VGA pecah jadi belasan segmen TCP; QVGA hanya 3-5. Makin sedikit
   segmen, makin kecil peluang satu di antaranya hilang.
3. **Pakai `firmware/rc_cam_esp32_ap/`** — lihat di bawah.

### Kamera sebagai Access Point

Pada susunan baku, kamera dan LattePanda sama-sama klien router GL.iNet.
Artinya setiap paket video menyeberang udara **dua kali** di kanal yang
sama — router menerimanya lalu memancarkannya ulang:

```
kamera ──udara──> GL.iNet ──udara──> LattePanda
```

`firmware/rc_cam_esp32_ap/` membuat kamera menjadi access point sendiri,
dan LattePanda menyambung langsung kepadanya. Kendali tetap lewat GL.iNet,
tapi disambungkan ke LattePanda lewat **kabel LAN**:

```
kamera(AP) ──udara──> LattePanda              1 hop, kanal sendiri
mobil ──udara──> GL.iNet ──kabel──> LattePanda
```

Airtime video jadi separuh, peluang kehilangan paket jadi separuh, dan
video tidak lagi berebut kanal dengan kendali. Untuk balapan 3 mobil tiap
kamera memakai kanal berbeda yang diturunkan dari `UNIT_ID` (1/6/11 —
ketiga kanal non-overlap 2,4 GHz), jadi tiap pasang punya kanal sendiri.

Cara memakainya:

1. Flash `rc_cam_esp32_ap/` (setel `UNIT_ID` seperti biasa).
2. Sambungkan LattePanda ke WiFi kamera — SSID `RCCam-<unit>`.
3. Sambungkan LattePanda ke GL.iNet lewat **kabel LAN**.
4. Di `ground/config.yaml`, buka komentar `stream_url` dan isi
   `http://192.168.4.1/stream`. Biarkan `car_ip` tetap diturunkan dari
   `unit:` — mobil tidak berubah sama sekali.

**Yang harus Anda uji sendiri:** antena XIAO ESP32S3 jauh lebih kecil
daripada antena GL.iNet, jadi sebagai AP **jangkauannya kemungkinan lebih
pendek**. Itu satu-satunya hal yang bisa membuat varian ini lebih buruk.
Uji jangkauan sebelum memakainya untuk balapan.

Varian asli (`rc_cam_esp32/`) tidak diubah dan tetap bisa dipakai kapan
saja — flash yang mana pun untuk membandingkan.

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
