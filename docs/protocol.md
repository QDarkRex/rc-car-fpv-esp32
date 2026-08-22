# Protokol Kendali RC Car — v3

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

Ukuran total: **13 byte**.

| Offset | Field | Tipe | Isi |
|---:|---|---|---|
| 0 | `magic[0]` | u8 | `'R'` (0x52) |
| 1 | `magic[1]` | u8 | `'C'` (0x43) |
| 2 | `version` | u8 | `3` |
| 3 | `unit_id` | u8 | **1, 2, atau 3** — mobil mana yang dituju |
| 4 | `seq` | u16 | nomor urut, membungkus di 65535 |
| 6 | `flags` | u8 | lihat tabel flag di bawah |
| 7 | `steer` | i16 | **−1000 … +1000** (negatif = kiri) |
| 9 | `throttle` | i16 | **−1000 … +1000** (negatif = mundur) |
| 11 | `brake` | u8 | **0 … 255**, `0` = tidak mengerem |
| 12 | `crc8` | u8 | CRC-8 dari byte 0..11 |

### Kenapa rem butuh field sendiri

`throttle` negatif sudah dipakai untuk mundur, jadi ia tidak bisa sekaligus
menyatakan "sedang mengerem" — kedua makna itu akan bentrok pada nilai yang
sama. `brake` karena itu berdiri sendiri sebagai besaran 0..255: seberapa
keras rem diinjak, lepas dari arah gerak mobil saat ini. Mobil boleh mengerem
sambil `throttle` masih membawa nilai maju/mundur terakhir; firmware yang
memutuskan prioritas mana yang menang (lihat `firmware/rc_car_esp32/drive.cpp`).

### Kenapa unit_id ada di paket ini

Dengan 3 mobil balapan di satu jaringan, `unit_id` adalah satu-satunya
pembeda antara "paket ini untuk saya" dan "paket ini untuk mobil sebelah".
Tanpa field ini, discovery broadcast (bagian 6) tidak mungkin aman dipakai
dengan lebih dari satu mobil di jaringan yang sama. Detail lengkap
alasannya, dan aturan pembuangannya, ada di bagian 7.

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

Ukuran total: **15 byte**. Dikirim ke alamat asal paket kontrol valid terakhir.

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
| 2 | `version` | u8 | `3` |
| 3 | `unit_id` | u8 | **1, 2, atau 3** — mobil mana yang mengirim, harus sama dengan `unit_id` di paket kontrol yang dibalasnya |
| 4 | `seq_echo` | u16 | `seq` paket kontrol valid terakhir yang diterima |
| 6 | `vbat_mv` | u16 | tegangan baterai dalam milivolt (mis. 15200 = 15,2 V) |
| 8 | `rssi` | i8 | kekuatan sinyal WiFi dalam dBm (mis. −55) |
| 9 | `flags` | u8 | lihat tabel flag di bawah |
| 10 | `uptime_ms` | u32 | milidetik sejak mobil menyala |
| 14 | `crc8` | u8 | CRC-8 dari byte 0..13 |

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
magic salah, `version` bukan 3, panjang tidak persis sesuai, atau CRC tidak cocok.
Paket yang dibuang **tidak** menyegarkan pewaktu failsafe.

Paket kontrol yang lolos semua pemeriksaan di atas tapi `unit_id`-nya bukan
milik mobil itu dibuang dengan aturan **yang sama persis**: tidak
menyegarkan pewaktu failsafe. Lihat bagian 7.

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

Mobil memakai IP statis (default `192.168.8.50` untuk unit 1, lihat bagian 7
untuk unit 2 dan 3), jadi dalam kondisi normal sisi darat langsung mengirim
unicast ke alamat itu.

Sebagai cadangan bila subnet berbeda: selama belum ada telemetri yang diterima,
sisi darat juga mengirim paket kontrol ke alamat **broadcast**. Mobil selalu
membalas telemetri ke alamat asal paket kontrol valid terakhir, sehingga sisi
darat belajar IP mobil dari balasan pertama, lalu mengunci ke unicast.

Selama fase broadcast ini sisi darat **tidak pernah** mengirim flag `ARMED` —
arming hanya diizinkan setelah tautan terkunci ke satu alamat unicast.

Dengan 3 mobil di satu jaringan, broadcast berarti KETIGA mobil menerima
paket broadcast yang sama. Tanpa penyaringan tambahan, ground station unit 1
bisa saja mengunci ke balasan mobil unit 2 kalau mobil itu yang kebetulan
membalas duluan — lihat bagian 7 untuk bagaimana `unit_id` mencegah ini,
dan kenapa itu membuat broadcast discovery tetap aman dipertahankan
walaupun ada banyak mobil di jaringan yang sama.

---

## 7. Balapan 3 mobil: unit_id dan pencegahan cross-control

Setiap mobil dan setiap ground station dikonfigurasi dengan satu **UNIT_ID**
tetap (1, 2, atau 3):

- Firmware mobil: `UNIT_ID` di `firmware/rc_car_esp32/config.h`.
- Firmware kamera: `UNIT_ID` di `firmware/rc_cam_esp32/rc_cam_esp32.ino`.
- Ground station: kunci `unit:` di `ground/config.yaml` (atau `--unit N` di
  command line).

Alamat IP mobil dan kamera **diturunkan** dari `UNIT_ID`, bukan diketik
manual satu-satu:

| Unit | IP mobil | IP kamera |
|---|---|---|
| 1 | 192.168.8.50 | 192.168.8.60 |
| 2 | 192.168.8.51 | 192.168.8.61 |
| 3 | 192.168.8.52 | 192.168.8.62 |

(`CAR_IP_4 = 49 + UNIT_ID`, `CAM_IP_4 = 59 + UNIT_ID` — di luar rentang DHCP
GL.iNet .100-.249, jadi tidak akan pernah bentrok dengan perangkat lain yang
minta IP otomatis.)

### Masalah nyata yang diperbaiki field unit_id

Sebelum v3, paket kontrol tidak membawa informasi "mobil mana yang dituju".
Dengan 3 mobil di satu jaringan, selama fase discovery broadcast (bagian 6)
ground station unit 1 bisa saja menerima balasan dari mobil unit 2 —
misalnya karena mobil unit 2 lebih dekat secara radio dan membalas duluan —
dan mengunci ke situ. Hasilnya: pembalap 1 memegang stir mobil 1, tapi yang
bergerak justru mobil 2. Saat balapan, dengan 3 mobil bergerak bersamaan,
ini berbahaya.

### Aturan penyaringan

**Di mobil** (`firmware/rc_car_esp32/link.cpp`, `CarLink::receivePackets()`):
paket kontrol yang lolos validasi CRC/magic/versi/panjang tapi `unit_id`-nya
bukan `UNIT_ID` milik mobil itu **dibuang**, dengan aturan yang **sama
persis** dengan paket rusak — **tidak menyegarkan pewaktu failsafe**.
Dihitung terpisah lewat `_foreignCount`, terlihat di perintah `status`
konsol serial sebagai "bukan-untuk-unit-ini", supaya operator bisa
membedakan "tidak ada paket sama sekali" dari "banyak paket tapi bukan
untuk mobil ini" (indikasi kuat ground station yang salah kunci unit).

**Di ground station** (`ground/rcground/link.py`, `Link._rx_loop()`):
telemetri yang lolos validasi tapi `unit_id`-nya bukan milik ground station
itu **dibuang SEBELUM sempat mengunci `locked_addr`** ke alamat pengirimnya.
Ini bagian yang paling penting: kalau penyaringan dilakukan SETELAH
mengunci, kerusakannya sudah terjadi — ground station sudah kadung
mengendalikan mobil yang salah. Dihitung terpisah lewat `foreign_count`.

### Kenapa broadcast discovery tetap aman dipertahankan

Dengan kedua sisi menyaring `unit_id` seperti di atas: broadcast boleh
terdengar oleh ketiga mobil sekaligus, tapi setiap mobil hanya BEREAKSI
terhadap paket dengan `unit_id` miliknya, dan setiap ground station hanya
BEREAKSI terhadap telemetri dengan `unit_id` miliknya. Efeknya sama dengan
seolah-olah masing-masing pasangan mobil/ground station berada di jaringan
terpisah, walau secara fisik berbagi satu WiFi dan satu port UDP. Karena itu
mekanisme discovery broadcast di bagian 6 tidak perlu diubah atau dibuang —
`unit_id` sudah cukup untuk membuatnya aman dipakai bersama 3 mobil.

### Cara memverifikasi tidak ada cross-control

Sebelum balapan, di konsol serial tiap mobil ketik `status` dan pastikan
`bukan-untuk-unit-ini` **tidak terus naik** selagi ground station unit lain
sedang aktif mengirim di jaringan yang sama. Kalau angka itu naik cepat,
berarti ground station lain memang "terdengar" oleh mobil ini — itu normal
selama `rx` (paket yang DITERIMA) tetap nol atau tidak berubah untuk unit
yang salah. Lihat juga `docs/balapan-3-unit.md` untuk checklist hari
balapan.
