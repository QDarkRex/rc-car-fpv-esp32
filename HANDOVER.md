# Handover — RC Car FPV ESP32

Dokumen ini untuk orang yang **melanjutkan** pekerjaan ini, bukan untuk
mempelajari cara memakainya. Untuk yang terakhir, baca [README.md](README.md)
— di sana ada arsitektur, cara merakit, dan cara menjalankan.

Yang ada di sini adalah hal-hal yang tidak bisa dibaca dari kode: apa yang
sudah berhasil, apa yang belum, keputusan apa yang sudah diambil beserta
alasannya, dan jebakan mana yang sudah memakan waktu supaya tidak dimakan
dua kali.

**Ditulis:** 27 Agustus 2026
**Commit terakhir:** `7d1e79d`

---

## 1. Baca ini dulu — keadaan tidak konsisten

`UNIT_ID` **tidak sinkron** di seluruh sistem saat serah terima ini. Ini
bukan bug, tapi pekerjaan yang tertinggal di tengah jalan, dan ia akan
membuat sistem tampak "rusak total" kalau tidak diketahui.

| Tempat | Berkas | Nilai |
|---|---|---|
| Firmware mobil | `firmware/rc_car_esp32/config.h` | **2** |
| Firmware kamera (STA) | `firmware/rc_cam_esp32/rc_cam_esp32.ino` | 3 |
| Firmware kamera (AP) | `firmware/rc_cam_esp32_ap/rc_cam_esp32_ap.ino` | 3 |
| Ground station (source) | `ground/config.yaml` | **2** |
| Ground station (exe) | `ground/dist/RCCarField/config.yaml` | 3 |

**Ketiganya harus sama.** Protokol v3 menyaring berdasarkan `unit_id`:
mobil **membuang** setiap paket yang bukan miliknya, tanpa pesan error apa
pun. Gejalanya menyesatkan — video bisa muncul normal (kalau kamera cocok)
sementara mobil sama sekali tidak merespons dan banner tidak pernah keluar
dari FAILSAFE.

Pemiliknya tampaknya sedang pindah ke unit 3. Untuk menuntaskan: setel
`UNIT_ID 3` di firmware mobil, flash ulang, dan samakan `ground/config.yaml`
ke `unit: 3`.

> **Jebakan:** `config.yaml` di folder exe **tertimpa setiap kali build**
> oleh versi dari `ground/`. Kalau hanya mengedit yang di folder exe,
> setelan itu hilang di build berikutnya.

---

## 2. Masalah yang BELUM selesai

### Video patah-patah — ini pekerjaan utama yang tersisa

Keluhan pemiliknya: **latensi masih bisa diterima, tapi patah-patahnya
membuat tidak nyaman dimainkan.** Ini dua masalah berbeda, dan yang kedua
yang belum terpecahkan.

**Diagnosis kerja (belum terbukti tuntas):** video mengalir lewat TCP. Satu
segmen hilang menahan **seluruh** aliran sampai kiriman ulangnya sampai —
video membeku, lalu frame menumpuk datang serentak. Pemiliknya
mengonfirmasi ada **ping RTO sepersekian detik** di jaringannya, yang
cocok sebagai pemicu.

**Sudah dicoba:**

| Tindakan | Hasil |
|---|---|
| Dekode JPEG pindah ke thread | Latensi turun sedikit; bukan hambatan utama |
| `CAM_JPEG_QUALITY` 16 → 20 | Latensi turun, dirasakan pemilik |
| `FRAMESIZE_QVGA` | **Belum benar-benar diuji** — sempat diset lalu dikembalikan ke VGA |
| Kamera jadi Access Point | Dilaporkan **makin patah** — belum didiagnosis |

**Belum dicoba sama sekali:**

- **Ganti kanal router.** Gratis, tanpa flash, dan sering paling
  berpengaruh terhadap RTO. Pilih 1/6/11 yang paling lengang.
- **QVGA sungguhan.** Frame VGA pecah jadi belasan segmen TCP; QVGA hanya
  3-5. Makin sedikit segmen, makin kecil peluang satu hilang.
- **Elko 470 µF** di jalur daya kamera (lihat `docs/wiring.md`). Kamera
  masih dicatu dari USB saja.

### Kenapa mode AP bisa lebih buruk — hipotesis yang belum diuji

Mode AP secara teori lebih baik: paket video menyeberang udara **sekali**
(kamera → darat) alih-alih dua kali (kamera → router → darat), dan video
mendapat kanal sendiri. Tapi hasil lapangannya justru lebih buruk. Tiga
tersangka, urut dari yang paling mudah diperiksa:

1. **Kanal 11 mungkin padat.** `UNIT_ID 3` memilih kanal 11. Kalau kanal
   itu ramai sementara router tadinya di kanal lengang, ini pindah ke
   kanal yang lebih buruk. Cek dengan
   `netsh wlan show networks mode=bssid`.
2. **ESP32 merangkap AP.** Selain kamera + JPEG + HTTP, kini juga beacon
   dan manajemen klien. Lihat fps yang dicetak Serial Monitor tiap 5 detik
   — kalau turun, ini penyebabnya.
3. **Windows background scan.** Saat tersambung ke jaringan tanpa internet
   (AP kamera memang tidak punya), Windows berkala memindai jaringan lain
   dan radionya meninggalkan kanal puluhan milidetik. Muncul sebagai patah
   berkala yang **berirama teratur** — kalau iramanya teratur, ini
   tersangkanya.

Varian AP ada di `firmware/rc_cam_esp32_ap/` sebagai **salinan terpisah**.
Varian asli `rc_cam_esp32/` tidak diubah, jadi bisa kembali kapan saja
hanya dengan flash ulang.

### Sudah diteliti dan DITOLAK: hx-esp32-cam-fpv

[github.com/RomanLut/hx-esp32-cam-fpv](https://github.com/RomanLut/hx-esp32-cam-fpv)
memakai raw 802.11 packet injection + FEC menggantikan TCP. Secara
struktural itu **obat yang tepat** untuk patah-patah (tidak ada retransmisi
= tidak ada pembekuan). Tetap ditolak karena:

- **Ground station Linux/Android saja** — proyek ini di Windows
- Butuh **dongle WiFi mode monitor**; pemilik punya Alfa AWUS1900
  (RTL8814AU) yang **tidak ada di daftar dukungan** proyek itu
- **"Hanya satu GS per Air Unit"**, dan multi-unit **tidak disarankan** —
  padahal balapan 3 mobil adalah tujuan proyek ini
- Perkiraan 6-10 malam kerja, dan menulis ulang kedua sisi

Jangan ulangi riset ini kecuali kebutuhan 3 mobil dibatalkan.

---

## 3. Keputusan yang sudah diambil — jangan dibalik tanpa membaca ini

Semuanya disengaja. Kalau terlihat aneh, alasannya ada di sini.

### Failsafe motor DIMATIKAN

`FAILSAFE_ENABLED 0` di firmware mobil, berpasangan dengan
`disarm_on_link_loss: false` di `config.yaml`.

Artinya: **kalau tautan putus saat gas ditekan, mobil terus melaju** dengan
perintah terakhir sampai paket kembali atau baterai dicabut. Ini permintaan
eksplisit pemiliknya — mobil kecil, bertenaga rendah, dipakai di track
khusus.

**Kalau menyalakannya lagi, ubah KEDUANYA.** Kalau hanya satu sisi, Anda
akan bingung kenapa mobil berhenti sendiri (atau tidak).

Yang **tidak** ikut dimatikan: aturan arming. Mobil tetap menyala dalam
keadaan disarmed dan tetap butuh transisi flag ARMED 0→1.

⚠️ **Checklist di README.md langkah 6 menjadi menyesatkan** — isinya
menyuruh menguji failsafe dan mengharapkan motor berhenti dalam 300 ms.
Dengan setelan sekarang, motor **tidak akan berhenti**. Itu bukan
kerusakan.

### Gigi maju tidak membatasi kecepatan

`gear_ratios: [1.00, 1.00, 1.00, 1.00, 1.00, 1.00]` — gigi 1 sampai 6
identik, semuanya 100%. Permintaan pemilik: gigi hanya untuk rasa, bukan
untuk membatasi.

**N dan R tetap fungsional** dan tidak terpengaruh daftar ini — keduanya
ditangani di cabang terpisah `_process_geared()` yang tidak pernah membaca
`gear_ratios`. Dikunci oleh `test_gears_cosmetic.py`.

Nilai lama yang membatasi: `[0.35, 0.55, 0.75, 0.90, 1.00, 1.00]`.

### Tenggang tautan 30 detik

`link_grace_ms: 30000`. Kedipan tautan yang lebih pendek dari ini
**diabaikan total** oleh tampilan, suara, dan `disarm_on_link_loss`.

Sebelum ini ada, RTO sepersekian detik — normal di 2,4 GHz padat — mengubah
tiga hal sekaligus: banner jadi FAILSAFE, HUD menampilkan DISARMED walau
mobil masih armed, dan **suara mesin dimatikan lalu dinyalakan ulang**
sehingga suara starter terdengar berulang-ulang saat mengemudi.

Konsekuensi yang disengaja: kalau tautan benar-benar mati, banner FAILSAFE
baru muncul setelah 30 detik. Indikator cepat yang tetap ada adalah baris
**TELEM** — jatuh ke 0 Hz dalam hitungan detik.

Syarat **arm** tetap memakai `link_timeout_ms: 500` mentah.

### PING di HUD mengukur KAMERA, bukan mobil

Baris **PING** = TCP ke port HTTP kamera. Ping mobil pindah ke baris
**KENDALI**, tidak dihapus — itu angka yang menentukan apakah mobil masih
menurut, dan ambangnya lebih ketat (hijau <30 ms vs <60 ms).

Diukur dengan TCP connect, bukan ICMP, karena ICMP di Windows butuh hak
administrator atau memanggil `ping.exe` lalu mengurai keluarannya yang
berubah mengikuti bahasa Windows.

⚠️ **Jangan percepat `ping_interval_s` di bawah ~1 detik.** Firmware kamera
hanya melayani **3 socket** dengan `lru_purge_enable`; stream memakai satu,
probe satu lagi sesaat. Kalau probe menumpuk sampai slot habis, LRU purge
bisa **memutus koneksi stream yang sedang berjalan**.

### fb_count = 3 (bukan 2)

Saat satu frame sedang dikirim lewat WiFi, handler menahan satu buffer.
Dengan `fb_count=2` sisanya hanya satu, jadi driver berhenti menangkap
begitu buffer itu penuh — dan `GRAB_LATEST` akhirnya memberi frame yang
sudah menunggu, bukan yang terbaru. Dengan 3, driver terus menangkap.

**Belum diverifikasi di hardware.** Satu subagen riset menyarankan justru
menurunkannya ke 2. Ini satu baris — ukur keduanya dengan baris PATAH dan
percayai angkanya, bukan argumen di komentar.

### Baris PATAH ada karena fps tidak bisa menggantikannya

`VIDEO fps` adalah rata-rata 2 detik, jadi **beku 400 ms lalu menyusul
beruntun tetap terbaca ~20 fps**. Terbukti terukur: pola itu menghasilkan
fps 16,8 (tampak sehat) sementara PATAH menangkapnya di 580 ms.

Ambang: <120 ms hijau, <250 ms kuning, di atas itu merah.

---

## 4. Jebakan yang sudah memakan waktu

**Windows Smart App Control memblokir toolchain ESP32.** Gejalanya di
Arduino IDE:

```
Failed to start child process: Os { code: 4551, ... "An Application
Control policy has blocked this file." }
```

Ini bukan masalah kode. Windows memblokir `xtensa-esp32-elf-gcc.exe`.
Matikan lewat Settings → Windows Security → App & browser control → Smart
App Control → Off, lalu **restart**. Kalau statusnya sudah "On" penuh
(bukan "Evaluation"), mematikannya butuh install ulang Windows.

**Stir tanpa `calibration.yaml` dulu mengarang input.** Sudah diperbaiki —
sekarang semua axis yang tidak terkalibrasi terbaca **0**. Dulu ia menebak
axis gas = 1 **dan** menebak pedal-lepas di −1.0; pada stir yang axis-nya
diam di 0.0 itu terbaca sebagai **gas 50% tanpa pedal disentuh**, sehingga
arming diblokir dengan pesan "lepaskan pedal dulu" yang menyesatkan.
Peringatan kalibrasi kini tampil sebagai pita kuning di HUD, bukan hanya
di konsol yang mudah terlewat. Dikunci oleh `test_wheel_uncalibrated.py`.

**Build gagal karena folder terkunci.** `build_exe.py` menghapus
`dist/RCCarField` lebih dulu. Kalau folder itu terbuka di Explorer, atau
sebuah shell sedang `cd` di dalamnya, penghapusan gagal dengan
`PermissionError: [WinError 32]`. Tutup Explorer, jangan biarkan terminal
berada di dalam folder itu.

**Servo yang mendengung menahan di ujung akan rusak dalam hitungan
menit.** Saat menyetel `SERVO_MIN_US`/`SERVO_MAX_US`, begitu terdengar
dengung, mundur 25 µs.

---

## 5. Keadaan hardware saat ini

| Setelan | Nilai | Catatan |
|---|---|---|
| `SERVO_MIN_US` (kanan) | 1000 | **Asimetris** — 200 µs ke kiri, 300 µs ke kanan dari tengah |
| `SERVO_CENTER_US` | 1200 | `drive.cpp` menghitung kedua sisi terpisah, jadi asimetri memang didukung |
| `SERVO_MAX_US` (kiri) | 1500 | |
| `SERVO_INVERT` | 1 | Fakta pemasangan hardware, bukan preferensi |
| `MOTOR_INVERT` | 1 | Terukur: tanpa ini, maju jadi mundur |
| `MOTOR_MIN_DUTY` | 900 | Tinggi karena Vs L298N hanya 5 V untuk motor 5-6 V |
| `max_forward` | 1.00 | **Jangan diturunkan** — di 0.30 motor tidak berputar sama sekali |
| `VBAT_DIVIDER_RATIO` | 5.545 | **Nilai teori, belum diukur multimeter** |
| `CAM_FRAMESIZE` | VGA | QVGA belum benar-benar diuji |
| `CAM_JPEG_QUALITY` | 20 | Dinaikkan dari 16, membantu |

**Perbaikan hardware sebenarnya** untuk `MOTOR_MIN_DUTY` yang setinggi itu
bukan di angka, tapi di hardware: naikkan Vs ke ~7,5-8 V, atau ganti driver
ke MOSFET seperti TB6612FNG (drop ~0,5 V vs L298N ~2,5 V).

**Belum dikerjakan:** elko 470 µF di jalur daya kamera, kalibrasi
`VBAT_DIVIDER_RATIO` dengan multimeter, uji jangkauan mode AP.

---

## 6. Cara kerja sehari-hari

### Menjalankan tanpa hardware

Semua bisa diuji di meja. Dari `ground/`, tiga terminal:

```bash
python fake_car.py --unit 2
```
```bash
python fake_cam.py
```
```bash
python main.py --car 127.0.0.1 --cam http://127.0.0.1:8080/stream
```

`fake_car.py --drop 35` membuang 35% paket — cara menguji ketahanan link
tanpa jaringan buruk sungguhan.

`--unit N` pada `fake_car.py` **harus cocok** dengan `unit:` di
`config.yaml`, kalau tidak simulatornya membuang paket persis seperti mobil
sungguhan.

### Test

```bash
python -m unittest discover -p "test_*.py"
```

42 test, semuanya lulus per commit `7d1e79d`. Tidak butuh hardware,
jaringan, atau audio. Jalankan sebelum tiap commit.

Test bukan sekadar formalitas di proyek ini — beberapa di antaranya
menangkap bug nyata yang sudah terjadi:
`test_wheel_uncalibrated.py` (gas hantu),
`test_link_grace.py` (suara starter berulang),
`test_video.py` (pembekuan yang tidak terlihat oleh fps).

### Build exe

```bash
python build_exe.py
```

Menghasilkan `dist/RCCarField/` berisi `RCCar.exe`, `Kalibrasi.exe`,
`Latensi.exe`, plus `config.yaml` dan `calibration.yaml` di sebelahnya.

`config.yaml` dan `calibration.yaml` sengaja **di luar** exe supaya bisa
diedit tanpa build ulang. Ini tidak otomatis benar di PyInstaller — lihat
catatan panjang di `rcground/config.py` soal `sys.frozen` dan
`sys.executable`. Kalau menambah skrip yang membaca berkas dengan
`Path(__file__)`, jebakan yang sama akan muncul lagi.

### Mengukur latensi

`Latensi.exe` (atau `python latency_test.py`) mengukur glass-to-glass:
arahkan kamera mobil ke layar kiri yang menampilkan penghitung, tekan
SPASI untuk membekukan, selisih dua angka itulah latensinya.

**Belum pernah dipakai untuk mendapat angka dasar.** Itu langkah pertama
yang paling berguna bagi penerus — tanpa angka dasar, tidak ada perubahan
yang bisa dinilai berhasil.

---

## 7. Peta kode

```
firmware/
  rc_car_esp32/       Otak mobil. config.h = semua setelan.
                      drive.cpp = motor/servo. link.cpp = UDP + failsafe.
                      console.cpp = perintah serial diagnostik.
  rc_cam_esp32/       Kamera sebagai KLIEN router. Varian baku.
  rc_cam_esp32_ap/    Kamera sebagai ACCESS POINT. Salinan terpisah;
                      hanya topologi jaringan yang beda, setelan gambar
                      sengaja identik supaya perbandingan adil.
  rc_car_diag/        Sketch diagnostik terpisah.

ground/
  main.py             Aplikasi utama + loop kendali 50 Hz.
  calibrate.py        Wizard stir. --servo untuk titik servo (mobil tidak
                      bisa jalan di mode ini -- dijamin protokol).
  latency_test.py     Pengukur latensi glass-to-glass.
  build_exe.py        PyInstaller.
  fake_car.py         Simulator mobil (--unit, --drop).
  fake_cam.py         Simulator kamera.
  rcground/
    link.py           UDP ke mobil, RTT, penyaringan unit_id.
    video.py          MJPEG + dekode di thread + CameraPing + worst_gap_ms.
    wheel.py          Baca stir, kurva, gigi, pemetaan servo.
    hud.py            Overlay HUD.
    sfx.py            Suara mesin/klakson/arm.
    config.py         Muat/simpan config, jebakan PyInstaller.

docs/
  protocol.md         SUMBER KEBENARAN paket UDP. Kalau diubah, ubah juga
                      firmware/rc_car_esp32/protocol.h DAN
                      ground/rcground/protocol.py -- ketiganya harus kembar.
  wiring.md           Perakitan, daya, pinout. Bagian 2 (Daya) wajib dibaca.
  balapan-3-unit.md   Setup 3 mobil.
  test-status.md      Checkpoint pengujian.
```

---

## 8. Tiga langkah pertama yang saya sarankan

1. **Tuntaskan `UNIT_ID`** (bagian 1). Tanpa ini, semua pengujian lain
   menyesatkan.
2. **Dapatkan angka dasar** dengan `Latensi.exe` dan baris PATAH, di mode
   STA (`rc_cam_esp32/`) yang sudah dikenal. Catat angkanya.
3. **Ubah satu hal, ukur lagi.** Urutan termurah: kanal router → QVGA →
   elko kamera. Jangan mengubah dua hal sekaligus.

Pola yang berlaku di seluruh proyek ini: **ukur dulu, baru ubah.** Sudah
beberapa kali perubahan "yang jelas membantu" ternyata tidak, dan yang
menyelesaikannya justru hal yang tidak diduga.
