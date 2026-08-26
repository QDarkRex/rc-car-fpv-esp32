// camera_pins.h — pemetaan pin modul kamera.
//
// Pin-pin ini DITENTUKAN OLEH MODUL, bukan pilihan kita. Jangan diubah
// kecuali Anda memakai modul kamera merek lain.
//
// Proyek ini bisa dipakai dengan DUA modul kamera berbeda. Pilih salah satu
// dengan mengubah angka di bawah ini SEBELUM meng-upload:
//
//   CAM_BOARD_XIAO_S3 = 1  -> Seeed Studio XIAO ESP32S3 Sense (modul asli
//                             yang dipakai proyek ini)
//   CAM_BOARD_XIAO_S3 = 0  -> AI-Thinker ESP32-CAM (modul cadangan/lama)
//
// Mengganti angka ini HARUS dibarengi mengganti board di Arduino IDE juga,
// kalau tidak sketch akan ter-upload dengan pinout yang salah untuk chip
// yang salah:
//
//   XIAO ESP32S3 Sense:
//     Board             : "XIAO_ESP32S3" (esp32:esp32:XIAO_ESP32S3)
//     Partition Scheme  : "Default with spiffs (3MB APP/1.5MB SPIFFS)"
//     PSRAM             : "OPI PSRAM"  <- WAJIB, modul ini punya PSRAM 8 MB
//                          lewat OPI, bukan QSPI biasa. Kalau dibiarkan
//                          "Disabled", esp_camera_init() akan gagal begitu
//                          resolusi dinaikkan di atas QVGA.
//
//   AI-Thinker ESP32-CAM:
//     Board             : "AI Thinker ESP32-CAM" (esp32:esp32:esp32cam)
//     Partition Scheme  : "Huge APP (3MB No OTA/1MB SPIFFS)"
//     PSRAM             : "Enabled"
//
// Sumber nilai pin: berkas contoh resmi core ESP32 yang terpasang di mesin
// ini, blok CAMERA_MODEL_XIAO_ESP32S3 dan CAMERA_MODEL_AI_THINKER di
// C:\Users\user\AppData\Local\Arduino15\packages\esp32\hardware\esp32\
// 3.3.10\libraries\ESP32\examples\Camera\CameraWebServer\camera_pins.h

#pragma once

#define CAM_BOARD_XIAO_S3 1

#if CAM_BOARD_XIAO_S3

// ---------------------------------------------- Seeed XIAO ESP32S3 Sense
//
// Modul ini punya konektor USB-C bawaan dan tidak punya LED flash terpisah
// seperti AI-Thinker, jadi tidak ada LED_FLASH_GPIO_NUM di sini.

#define PWDN_GPIO_NUM -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 10
#define SIOD_GPIO_NUM 40
#define SIOC_GPIO_NUM 39

#define Y9_GPIO_NUM 48
#define Y8_GPIO_NUM 11
#define Y7_GPIO_NUM 12
#define Y6_GPIO_NUM 14
#define Y5_GPIO_NUM 16
#define Y4_GPIO_NUM 18
#define Y3_GPIO_NUM 17
#define Y2_GPIO_NUM 15

#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM 47
#define PCLK_GPIO_NUM 13

#else

// ---------------------------------------------- AI-Thinker ESP32-CAM
//
// Konsekuensi yang perlu diketahui saat merakit: hampir semua GPIO yang enak
// dipakai sudah habis untuk kamera. Karena itu ESP32-CAM di proyek ini hanya
// bertugas mengirim video, sementara motor dan servo ditangani ESP32 dev
// module yang terpisah.

#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27

#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5

#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

// LED flash putih terang di sisi papan. Menyalakannya menarik arus besar,
// jadi dibiarkan mati; hanya disiapkan sebagai output agar tidak mengambang.
#define LED_FLASH_GPIO_NUM 4

#endif  // CAM_BOARD_XIAO_S3
