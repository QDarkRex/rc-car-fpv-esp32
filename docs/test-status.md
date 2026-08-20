# Status Pengujian Terakhir

Tanggal checkpoint: **20 Agustus 2026**

Dokumen ini mencatat kondisi terakhir yang sudah benar-benar diuji. Gunakan
sebagai titik mulai sesi berikutnya agar pengujian yang sudah selesai tidak
perlu diulang tanpa alasan.

## Lingkungan pengujian

- Ground station masih dijalankan di **laptop Windows ini**, belum di
  LattePanda.
- Komponen dan wiring yang tercantum di `docs/wiring.md` sudah tersedia dan
  sudah dirakit oleh pengguna.
- Mobil masih diuji melalui simulator; ESP32 pengendali motor dan servo belum
  dinyatakan lulus uji hardware.
- Modul kamera sebenarnya adalah **Seeed Studio XIAO ESP32S3 Sense**, bukan
  AI Thinker ESP32-CAM.

## Hasil yang sudah lulus

### PXN V9

Kalibrasi selesai dan tersimpan di `ground/calibration.yaml`:

| Fungsi | Hasil kalibrasi |
|---|---|
| Perangkat | `V9GEN2`, joystick index 0 |
| Stir | axis 0, min −1, center 0,0217, max +1 |
| Gas | axis 2, released −1, pressed +1 |
| Rem | axis 5, released −1, pressed +1 |
| Tombol ARM | button 0 |
| Emergency stop | button 1 |
| Shifter | H-pattern |
| Gigi 1–6 | button 16–21 |
| Mundur | button 22 |

Saklar mode PXN tidak boleh digeser setelah kalibrasi. Jika mode diubah,
jalankan ulang `ground/calibrate.py`.

### Ground station dan link simulator

- Simulator mobil terkunci ke `127.0.0.1:4210` melalui UDP.
- Laju kontrol terukur stabil di **49,5–50,0 Hz**.
- Simulator melaporkan `failsafe=False` selama ground station berjalan.
- Arming dengan PXN berhasil setelah shifter berada di netral dan pedal
  dilepas; hasil ini sudah dikonfirmasi pengguna.
- Uji terakhir dijalankan dengan `--no-video` untuk mengisolasi jalur kontrol.

Perintah uji yang digunakan:

```powershell
cd "C:\Users\user\Documents\RC Car\ground"
python main.py --car 127.0.0.1 --no-video
```

## Perbaikan yang sudah diterapkan

1. Pemanggilan `_build_context()` di `ground/main.py` sekarang meneruskan
   `brake_out` dengan benar.
2. `HudContext` memiliki field `brake_out`, `gear`, dan `gear_label` yang
   dibutuhkan ground station.
3. Loop reconnect joystick sudah diperbaiki. Sebelumnya urutannya adalah
   `JOYDEVICEADDED -> reconnect -> JOYDEVICEADDED`, sehingga loop kontrol
   turun menjadi sekitar 6 Hz dan link terlihat putus-nyambung. Event ADDED
   sekarang hanya melakukan reconnect bila wheel memang belum aktif.
4. File Python yang berubah sudah lulus `py_compile`.
5. Firmware `firmware/rc_cam_esp32` sudah di-port dari AI-Thinker ESP32-CAM
   ke Seeed XIAO ESP32S3 Sense: `camera_pins.h` diganti dengan pinout resmi
   XIAO (dan tetap menyimpan pinout AI-Thinker sebagai pilihan cadangan
   lewat `CAM_BOARD_XIAO_S3`), LED flash AI-Thinker-only dijaga dengan
   `#if`, dan komentar header/prosedur flash diperbarui. Terkompilasi
   bersih untuk kedua target: `esp32:esp32:XIAO_ESP32S3:PSRAM=opi` dan
   `esp32:esp32:esp32cam`. Belum diuji di hardware sungguhan.

## Belum selesai

- Firmware `firmware/rc_cam_esp32` sudah di-port ke XIAO ESP32S3 Sense
  (lihat "Perbaikan yang sudah diterapkan" di bawah), tapi **belum diuji di
  hardware sungguhan** — baru lulus kompilasi. Kredibilitas jalur video
  (fps, kestabilan WiFi, brownout) masih harus dibuktikan dengan modul
  fisik.
- Keputusan final jalur daya XIAO ditunda. Jangan menyambungkan 5 V melalui
  BAT85 ke pin BAT; jalur daya akan ditentukan sebelum uji kamera hardware.
  Rencana sementara (lihat `docs/wiring.md` bagian 7a): pin `5V` XIAO
  disambung ke step-down #2, sama seperti modul kamera sebelumnya.
- Kredensial hotspot sudah diisi di kedua firmware (`WIFI_SSID "RCCar"`,
  `WIFI_PASS "admin.admin"`), tapi belum dicoba menyambung ke hotspot
  sungguhan.
- ESP32 Dev Module belum dicatat sebagai sudah di-flash dan diuji dengan
  motor/servo sungguhan.
- Failsafe hardware 300 ms belum diuji dengan roda di udara.
- ESP32-CAM/XIAO belum diuji streaming melalui hotspot.
- Aplikasi belum dipindahkan dan diuji di LattePanda.

## Langkah berikutnya

1. Pertahankan `throttle.max_forward` di sekitar 0,30 untuk uji hardware awal.
2. Isi WiFi, flash ESP32 Dev Module, lalu uji servo dan motor dengan roda di
   udara.
3. Uji failsafe hardware dengan mematikan hotspot saat motor berputar pelan.
4. Adaptasi firmware kamera ke XIAO ESP32S3 Sense sudah selesai dan
   terkompilasi; tinggal flash dan uji stream terpisah di hardware
   sungguhan.
5. Setelah laptop stabil dengan hardware, pindahkan ground station ke
   LattePanda dan ulangi uji link/failsafe.
