# Protokol Kendali RC Car — v2

Dokumen ini adalah **sumber kebenaran tunggal**. Dua implementasi harus selalu
kembar dengan dokumen ini:

- `firmware/rc_car_esp32/protocol.h` (C++, sisi mobil)
- `ground/rcground/protocol.py` (Python, sisi darat)

Kalau salah satu diubah, ubah ketiganya.

---

## 1. Transport

| | |
|---|---|
| Protokol | UDP |
| Port mobil | **4210** |
| Port darat | ephemeral (mobil membalas ke alamat asal paket) |
| Byte order | **little-endian**, tanpa padding/alignment |
| Laju kontrol | 50 Hz (setiap 20 ms) |
| Laju telemetri | dibalas pada tiap paket kontrol ke-5 → 10 Hz |

### Kenapa UDP tanpa retransmisi

Untuk kendali real-time, paket yang **telat** lebih berbahaya daripada paket
yang **hilang**. Pada 50 Hz, paket berikutnya sudah tiba 20 ms kemudian —
mengirim ulang paket lama justru akan mengeksekusi perintah yang sudah basi.
Karena itu tidak ada ACK, tidak ada retry, dan paket yang datang tidak berurutan
langsung dibuang berdasarkan nomor urut.

---

## 2. Paket Kontrol (darat → mobil)

Ukuran total: **12 byte**.

| Offset | Field | Tipe | Isi |
|---:|---|---|---|
| 0 | `magic[0]` | u8 | `'R'` (0x52) |
| 1 | `magic[1]` | u8 | `'C'` (0x43) |
| 2 | `version` | u8 | `2` |
| 3 | `seq` | u16 | nomor urut, membungkus di 65535 |
| 5 | `flags` | u8 | lihat tabel flag di bawah |
| 6 | `steer` | i16 | **−1000 … +1000** (negatif = kiri) |
| 8 | `throttle` | i16 | **−1000 … +1000** (negatif = mundur) |
| 10 | `brake` | u8 | **0 … 255**, `0` = tidak mengerem |
| 11 | `crc8` | u8 | CRC-8 dari byte 0..10 |

### Kenapa rem butuh field sendiri

`throttle` negatif sudah dipakai untuk mundur, jadi ia tidak bisa sekaligus
menyatakan "sedang mengerem" — kedua makna itu akan bentrok pada nilai yang
sama. `brake` karena itu berdiri sendiri sebagai besaran 0..255: seberapa
keras rem diinjak, lepas dari arah gerak mobil saat ini. Mobil boleh mengerem
sambil `throttle` masih membawa nilai maju/mundur terakhir; firmware yang
memutuskan prioritas mana yang menang (lihat `firmware/rc_car_esp32/drive.cpp`).

### Kenapa gigi tidak ada di paket ini

Perhitungan gigi seluruhnya berada di sisi darat. Darat sudah membatasi
`throttle` yang dikirim sesuai rasio gigi yang sedang aktif sebelum paket
dikirim — ESP32 tidak pernah tahu mobil "sedang di gigi berapa", ia hanya
melihat angka throttle yang sudah jadi. Ini disengaja: rasio gigi bisa diubah
(`ground/config.yaml` → `shifter.gear_ratios`) tanpa flash ulang firmware
mobil sama sekali.

### Flag paket kontrol

| Bit | Nama | Arti |
|---:|---|---|
| 0 | `ARMED` | Mobil boleh menggerakkan motor. Jika 0, mobil **wajib** menetralkan motor. |
| 1–7 | — | dicadangkan, harus 0 |

---

## 3. Paket Telemetri (mobil → darat)

Ukuran total: **14 byte**. Dikirim ke alamat asal paket kontrol valid terakhir.

**Pemicunya adalah paket kontrol, bukan timer.** Mobil membalas telemetri saat
menerima paket kontrol valid yang `seq`-nya habis dibagi 5. Pada laju kontrol
50 Hz ini menghasilkan tepat 10 Hz.

Alasannya soal ketepatan pengukuran: kalau telemetri dikirim dari timer bebas,
`seq_echo` yang dibawanya bisa sudah menunggu hingga 100 ms sebelum terkirim,
dan angka "ping" di HUD ikut memuat waktu tunggu itu — terbaca puluhan
milidetik padahal jaringannya sehat. Dengan membalas langsung pada paketnya,
RTT yang terukur benar-benar waktu tempuh pulang-pergi. Ini terverifikasi:
pengujian loopback menghasilkan 1,4 ms, bukan 21 ms seperti pada rancangan
berbasis timer.

| Offset | Field | Tipe | Isi |
|---:|---|---|---|
| 0 | `magic[0]` | u8 | `'R'` (0x52) |
| 1 | `magic[1]` | u8 | `'T'` (0x54) |
| 2 | `version` | u8 | `2` |
| 3 | `seq_echo` | u16 | `seq` paket kontrol valid terakhir yang diterima |
| 5 | `vbat_mv` | u16 | tegangan baterai dalam milivolt (mis. 15200 = 15,2 V) |
| 7 | `rssi` | i8 | kekuatan sinyal WiFi dalam dBm (mis. −55) |
| 8 | `flags` | u8 | lihat tabel flag di bawah |
| 9 | `uptime_ms` | u32 | milidetik sejak mobil menyala |
| 13 | `crc8` | u8 | CRC-8 dari byte 0..12 |

### Flag telemetri

| Bit | Nama | Arti |
|---:|---|---|
| 0 | `ARMED` | Mobil sedang armed |
| 1 | `FAILSAFE` | Tautan kontrol sedang putus |
| 2 | `LOW_BATT` | Tegangan baterai di bawah ambang aman |
| 3–7 | — | dicadangkan, harus 0 |

`FAILSAFE` dan `ARMED` adalah dua hal berbeda dan tidak boleh dicampur.
`FAILSAFE` semata-mata soal **kesehatan tautan** — ia menyala saat paket
kontrol berhenti dan padam segera setelah paket valid mengalir lagi.
Boleh-tidaknya motor bergerak diatur terpisah oleh `ARMED`. Mobil yang
tersambung baik tetapi sengaja disarmed melaporkan `FAILSAFE = 0`, `ARMED = 0`.

### Cara menghitung RTT

`seq_echo` adalah gema dari nomor urut kontrol. Sisi darat menyimpan waktu
kirim setiap `seq`; saat telemetri tiba, RTT = sekarang − waktu_kirim(`seq_echo`).
Tidak perlu jam yang sinkron antara kedua sisi.

---

## 4. CRC-8

Polinomial `0x07` (CRC-8/ATM), init `0x00`, tanpa refleksi, tanpa XOR akhir.

```c
uint8_t crc8(const uint8_t *data, size_t len) {
    uint8_t crc = 0;
    while (len--) {
        crc ^= *data++;
        for (uint8_t i = 0; i < 8; i++)
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
    return crc;
}
```

Paket yang gagal salah satu dari ini **dibuang tanpa efek apa pun**:
magic salah, `version` bukan 2, panjang tidak persis sesuai, atau CRC tidak cocok.
Paket yang dibuang **tidak** menyegarkan pewaktu failsafe.

---

## 5. Failsafe

Aturan yang dijalankan firmware mobil:

1. Mobil **menyala dalam keadaan disarmed**. Motor netral, servo di tengah.
2. Perintah gerak hanya dieksekusi bila flag `ARMED` bernilai 1.
3. Bila tidak ada paket kontrol **valid** selama **300 ms**
   (`FAILSAFE_TIMEOUT_MS`), mobil masuk failsafe: throttle nol, servo ke tengah,
   status kembali disarmed.
4. Keluar dari failsafe **tidak otomatis**. Setelah paket kembali mengalir,
   mobil tetap disarmed sampai sisi darat mengirim transisi flag `ARMED`
   dari 0 → 1. Ini mencegah mobil melompat jalan sendiri begitu WiFi pulih.

### Cara mengunci aturan nomor 4 — jangan sampai salah

Deteksi transisi 0 → 1 dilakukan dengan membandingkan flag paket sekarang
terhadap flag paket sebelumnya (`prev_armed_flag`). Saat masuk failsafe,
variabel itu harus **dikunci ke 1**, bukan direset ke 0:

```c
// BENAR
prev_armed_flag = true;   // paksa sisi darat mengirim 0 dulu

// SALAH — mobil akan arm sendiri
prev_armed_flag = false;
```

Kalau direset ke 0, paket pertama yang tiba setelah WiFi pulih — yang masih
membawa `ARMED = 1` dari sebelum putus — akan terlihat seperti transisi 0 → 1
yang baru. Mobil arm sendiri dan langsung melaju, justru pada saat operator
belum tentu siap. Ini persis skenario yang aturan nomor 4 ingin cegah.

Versi awal `fake_car.py` mengandung bug ini dan tertangkap oleh pengujian
sebelum ada hardware yang tersambung. Firmware dan simulator kini sama-sama
mengunci ke 1. Kalau Anda menulis ulang bagian ini, uji ulang skenarionya:
arm → putuskan paket >300 ms → kirim lagi dengan flag `ARMED` tetap 1 →
mobil **harus** tetap disarmed.

Sisi darat menegakkan aturan tambahan: flag `ARMED` hanya boleh dikirim setelah
pengguna menekan tombol arm **dan** pedal gas berada di netral.

---

## 6. Penemuan alamat (discovery)

Mobil memakai IP statis (default `192.168.137.50`), jadi dalam kondisi normal
sisi darat langsung mengirim unicast ke alamat itu.

Sebagai cadangan bila subnet berbeda: selama belum ada telemetri yang diterima,
sisi darat juga mengirim paket kontrol ke alamat **broadcast**. Mobil selalu
membalas telemetri ke alamat asal paket kontrol valid terakhir, sehingga sisi
darat belajar IP mobil dari balasan pertama, lalu mengunci ke unicast.

Selama fase broadcast ini sisi darat **tidak pernah** mengirim flag `ARMED` —
arming hanya diizinkan setelah tautan terkunci ke satu alamat unicast.
