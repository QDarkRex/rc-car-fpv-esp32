/*
 * rc_cam_esp32_ap — kamera FPV untuk RC Car, VARIAN ACCESS POINT.
 *
 * ====================================================================
 * INI SALINAN TERPISAH DARI firmware/rc_cam_esp32/.
 * Yang asli TIDAK diubah dan tetap bisa dipakai kapan saja.
 * Bedanya HANYA topologi jaringan; semua setelan gambar (resolusi,
 * kualitas, orientasi, fb_count) sengaja dibiarkan SAMA PERSIS supaya
 * perbandingan antara keduanya mengukur topologinya saja.
 * ====================================================================
 *
 * MASALAH YANG DIPECAHKAN: video patah-patah.
 *
 * Pada varian asli, kamera menjadi klien router GL.iNet, dan LattePanda
 * juga klien router yang sama. Artinya setiap paket video menyeberang
 * udara DUA KALI di kanal yang sama:
 *
 *     kamera --udara--> GL.iNet --udara--> LattePanda
 *
 * Router harus menerima frame lalu memancarkannya ulang. Airtime terpakai
 * dua kali lipat, dan ada dua kesempatan paket hilang. Paket kendali 50 Hz
 * ikut berebut kanal yang sama. Di TCP, satu paket hilang menahan seluruh
 * aliran sampai kiriman ulangnya sampai -- itulah pembekuan yang terasa
 * sebagai patah-patah.
 *
 * Varian ini membuat kamera menjadi ACCESS POINT sendiri, dan LattePanda
 * menyambung langsung kepadanya:
 *
 *     kamera(AP) --udara--> LattePanda          <- SATU hop, kanal sendiri
 *     mobil --udara--> GL.iNet --KABEL LAN--> LattePanda
 *
 * Hasilnya: airtime video separuh, peluang kehilangan paket separuh, dan
 * video tidak lagi berebut kanal dengan kendali sama sekali.
 *
 * KONSEKUENSI YANG HARUS DIUKUR SENDIRI: antena XIAO ESP32S3 jauh lebih
 * kecil daripada antena GL.iNet. Sebagai AP, JANGKAUANNYA kemungkinan
 * lebih pendek. Itu satu-satunya hal yang bisa membuat varian ini lebih
 * buruk, dan hanya lapangan yang bisa membuktikannya. Uji jangkauan
 * sebelum memakainya untuk balapan.
 *
 * CARA MEMAKAI DI SISI DARAT:
 *   1. Sambungkan LattePanda ke WiFi kamera (SSID di CAM_AP_SSID bawah).
 *   2. Sambungkan LattePanda ke GL.iNet lewat KABEL LAN (untuk kendali).
 *   3. Di ground/config.yaml, buka komentar baris stream_url dan isi:
 *        stream_url: http://192.168.4.1/stream
 *      Biarkan network.car_ip tetap diturunkan dari unit: seperti biasa --
 *      mobil tetap lewat GL.iNet, tidak berubah sama sekali.
 *
 *   Subnet kamera (192.168.4.x) sengaja BERBEDA dari GL.iNet (192.168.8.x)
 *   supaya Windows bisa merutekan keduanya sekaligus lewat on-link route:
 *   192.168.8.51 keluar lewat LAN, 192.168.4.1 lewat WiFi.
 *
 * BALAPAN 3 MOBIL: tiap kamera memakai kanal berbeda yang diturunkan dari
 * UNIT_ID (1 -> kanal 1, 2 -> kanal 6, 3 -> kanal 11), yaitu ketiga kanal
 * non-overlap di 2,4 GHz. Setiap pasang kamera/LattePanda karena itu punya
 * kanal sendiri, sementara kendali ketiga mobil tetap lewat satu GL.iNet
 * (trafiknya kecil, ~5 kbps per mobil). Ini justru lebih longgar daripada
 * varian asli, di mana semuanya berdesakan di satu kanal.
 *
 * Sengaja BUKAN contoh CameraWebServer bawaan. UI kontrol di contoh itu
 * memakan RAM dan menambah latensi tanpa manfaat di sini; yang kita butuhkan
 * hanya satu stream MJPEG secepat mungkin.
 *
 * Sketch ini mendukung DUA modul kamera; pilih salah satu lewat
 * CAM_BOARD_XIAO_S3 di camera_pins.h, lalu cocokkan setelan board di
 * Arduino IDE dengan tabel di sana. Modul utama proyek ini adalah XIAO
 * ESP32S3 Sense.
 *
 *   XIAO ESP32S3 Sense (default, CAM_BOARD_XIAO_S3 = 1):
 *     Board             : "XIAO_ESP32S3"
 *     Partition Scheme  : "Default with spiffs (3MB APP/1.5MB SPIFFS)"
 *     PSRAM             : "OPI PSRAM"
 *
 *   AI-Thinker ESP32-CAM (cadangan, CAM_BOARD_XIAO_S3 = 0):
 *     Board             : "AI Thinker ESP32-CAM"
 *     Partition Scheme  : "Huge APP (3MB No OTA/1MB SPIFFS)"
 *     PSRAM             : "Enabled"
 *
 * Endpoint (alamat AP, sama untuk semua unit karena tiap kamera adalah
 * jaringan tersendiri -- tidak mungkin bentrok):
 *   http://192.168.4.1/         halaman pratinjau sederhana
 *   http://192.168.4.1/stream   stream MJPEG yang dipakai ground station
 *
 * CARA FLASH:
 *
 *   XIAO ESP32S3 Sense punya USB-C bawaan, jadi flash langsung lewat kabel
 *   USB-C ke laptop, pilih port-nya di Arduino IDE, lalu Upload. Tidak perlu
 *   adapter FTDI dan tidak perlu jumper GPIO0-GND.
 *
 *   Kalau board tidak terdeteksi (port tidak muncul, atau upload gagal di
 *   awal), masuk mode bootloader manual (prosedur resmi Seeed): tahan
 *   tombol BOOT tanpa dilepas, sambungkan kabel USB-C ke komputer sambil
 *   BOOT tetap ditahan, baru lepas BOOT setelah komputer mendeteksi port.
 *   Kalau kabel sudah tersambung, alternatifnya: tahan BOOT, tekan RESET
 *   sekali sambil BOOT masih ditahan, baru lepas BOOT.
 *
 *   AI-Thinker ESP32-CAM tidak punya USB, jadi butuh adapter FTDI/CH340
 *   3,3V (TX->U0R, RX->U0T, GND->GND, 5V->5V), GPIO0 dijumper ke GND saat
 *   upload, lalu jumper dilepas dan modul di-reset lagi setelahnya. Lihat
 *   docs/wiring.md untuk detail lengkap kedua modul.
 *
 * Perhatian daya:
 *   Menurut spesifikasi vendor, XIAO ESP32S3 Sense menarik sekitar
 *   100-150 mA saat WiFi aktif; kamera + WiFi bersamaan bisa lebih tinggi
 *   dan belum diukur langsung di proyek ini. AI-Thinker ESP32-CAM menarik
 *   lonjakan ~310 mA. Kedua kasus sama-sama butuh elko di jalur 5V/3V3-nya;
 *   brownout saat transmit adalah penyebab nomor satu modul kamera ESP32
 *   yang boot-loop.
 */

#include <WiFi.h>
#include <lwip/sockets.h>

#include "camera_pins.h"
#include "esp_camera.h"
#include "esp_http_server.h"

// ----------------------------------------------------------------- setelan

// =================================================================
// UNIT_ID -- SATU-SATUNYA BARIS YANG PERLU DIUBAH SAAT FLASH KAMERA
// KE-2 DAN KE-3. Isi 1, 2, atau 3, HARUS SAMA dengan UNIT_ID di
// firmware/rc_car_esp32/config.h milik mobil yang sama.
//
// Di varian AP ini, yang diturunkan dari UNIT_ID adalah NAMA SSID
// ("RCCam-1/2/3") dan KANAL (1/6/11) -- bukan alamat IP, karena tiap
// kamera adalah jaringan tersendiri dan semuanya memakai 192.168.4.1.
// Lihat blok jaringan (AP) di bawah.
// =================================================================
#define UNIT_ID 3

// ---------------------------------------------------------- jaringan (AP)
//
// Kamera ini MEMBUAT jaringan sendiri; ia tidak menyambung ke GL.iNet.
// SSID dibedakan per unit supaya tiga kamera bisa hidup bersamaan tanpa
// pembalap tertukar menyambung ke kamera mobil sebelah.
#define CAM_AP_SSID_BASE "RCCam-"
#define CAM_AP_PASS "admin.admin"      // minimal 8 karakter; "" = terbuka

// KANAL, diturunkan dari UNIT_ID: 1 -> 1, 2 -> 6, 3 -> 11.
//
// Ketiganya adalah satu-satunya kanal yang benar-benar TIDAK saling
// tumpang tindih di 2,4 GHz. Inilah inti keuntungan varian AP untuk
// balapan: tiap pasang kamera/LattePanda mendapat kanalnya sendiri,
// alih-alih berdesakan di satu kanal milik router.
//
// Setel GL.iNet ke kanal yang TIDAK dipakai kamera mana pun kalau bisa;
// kalau terpaksa berbagi, pilih kanal kamera unit yang paling jauh dari
// pembalap -- trafik kendali sangat kecil (~5 kbps per mobil) sehingga
// paling tahan terhadap gangguan.
#define CAM_AP_CHANNEL ((UNIT_ID) == 1 ? 1 : ((UNIT_ID) == 2 ? 6 : 11))

// Alamat AP. SAMA untuk semua unit -- tidak bentrok karena tiap kamera
// adalah jaringan terpisah yang hanya dilihat oleh satu LattePanda.
// Subnet 192.168.4.x sengaja BERBEDA dari GL.iNet (192.168.8.x) supaya
// LattePanda bisa memakai keduanya sekaligus: mobil lewat kabel LAN,
// kamera lewat WiFi, dan Windows merutekan otomatis lewat on-link route.
#define CAM_AP_IP_1 192
#define CAM_AP_IP_2 168
#define CAM_AP_IP_3 4
#define CAM_AP_IP_4 1

// Hanya LattePanda yang boleh menyambung. Membatasi ke 1 membuat kamera
// menolak klien nyasar yang akan ikut memakan airtime.
#define CAM_AP_MAX_CLIENTS 1

// 0 = SSID disiarkan seperti biasa. Set 1 untuk menyembunyikannya kalau
// lokasi balapan ramai dan Anda tidak ingin orang lain mencoba menyambung.
#define CAM_AP_HIDDEN 0

// =================================================================
// RESOLUSI KAMERA -- ganti SATU baris ini kalau 3 stream bersamaan
// membuat jaringan tersendat, lalu flash ulang KETIGA kamera.
//
//   FRAMESIZE_VGA  (640x480, dipakai sekarang)
//     ~3,5-5 Mbps per kamera. Dengan 3 mobil balapan bersamaan itu
//     berarti total ~10-15 Mbps hanya untuk video, berebut dengan paket
//     kendali 50 Hz di jaringan 2,4 GHz yang sama -- BERISIKO membuat
//     video atau kendali tersendat kalau ketiganya aktif sekaligus.
//
//   FRAMESIZE_QVGA (320x240)
//     ~1,5 Mbps per kamera. Tiga kamera bersamaan total ~4,5 Mbps --
//     AMAN, menyisakan banyak ruang untuk paket kendali. Gambar lebih
//     kecil tapi masih cukup untuk mengemudi FPV.
//
// Cara ganti: ubah baris CAM_FRAMESIZE di bawah, lalu flash ulang ketiga
// modul kamera (semuanya, supaya bandwidth turun serentak -- kalau cuma
// sebagian yang diturunkan, sisanya tetap membebani jaringan yang sama).
//
// DITURUNKAN KE QVGA untuk mengatasi VIDEO PATAH-PATAH, bukan sekadar
// menghemat bandwidth. Sebabnya spesifik pada video lewat TCP:
//
//   Satu frame VGA (~15-30 KB) pecah menjadi belasan segmen TCP. Kalau SATU
//   saja hilang, TCP menahan SELURUH aliran sampai kiriman ulangnya sampai
//   -- video membeku, lalu frame menumpuk datang serentak. Itulah rasa
//   patah-patah, dan makin banyak segmen per frame, makin sering satu di
//   antaranya kena.
//
//   QVGA (~4-8 KB) hanya butuh sekitar 3-5 segmen. Peluang satu frame
//   terkena kehilangan paket turun drastis, dan kalaupun kena, yang harus
//   dikirim ulang jauh lebih kecil sehingga bekunya lebih pendek.
//
// Pilihan lain kalau QVGA terasa terlalu kecil -- semuanya satu baris:
//   FRAMESIZE_CIF   (400x296) jalan tengah; proyek FPV lain melaporkan
//                   latensi terbaiknya justru di sekitar resolusi ini
//   FRAMESIZE_HVGA  (480x320) lebih besar sedikit dari CIF
//   FRAMESIZE_VGA   (640x480) nilai lama, gambar paling tajam tapi paling
//                   rentan patah di jaringan yang padat
//
// Ukur dengan baris PATAH di HUD sebelum dan sesudah mengganti, jangan
// mengandalkan perasaan -- baris VIDEO (fps) sengaja TIDAK bisa menunjukkan
// pembekuan karena ia rata-rata.
#define CAM_FRAMESIZE FRAMESIZE_VGA

// 10 = kualitas terbaik, 63 = terburuk. Angka lebih besar = frame lebih kecil
// = lebih tahan terhadap sinyal lemah.
//
// Diturunkan satu tingkat dari 12 ke 16. Frame biasanya menyusut sekitar
// 25-30%, jadi lebih sedikit data yang harus lewat WiFi tiap frame -- itu
// mengurangi rebutan bandwidth dengan paket kendali, dan biasanya terlihat
// sebagai fps naik plus stutter berkurang. Detail halus sedikit berkurang,
// tapi untuk mengemudi hampir tidak terasa.
//
// Dinaikkan lagi 16 -> 20 bersamaan dengan turun ke QVGA di atas, dengan
// alasan yang sama: memperkecil jumlah segmen TCP per frame supaya lebih
// sedikit yang bisa hilang. Efeknya menumpuk dengan QVGA -- frame akhirnya
// tinggal sekitar 3-6 KB.
//
// Kalau gambar terasa terlalu kasar setelah ini, TURUNKAN angka ini dulu
// (mis. ke 16) sebelum menaikkan resolusi kembali: menambah kualitas pada
// QVGA jauh lebih murah dari segi jumlah paket daripada naik ke VGA.
#define CAM_JPEG_QUALITY 20

// Orientasi gambar. Dua saklar independen, bukan satu "rotasi", karena
// sensor memang hanya mengenal dua operasi: balik vertikal dan cermin
// horizontal. Kombinasinya menutup keempat orientasi yang mungkin:
//
//   VFLIP  HMIRROR   hasil
//     0       0      normal
//     1       1      diputar 180 derajat
//     0       1      dicerminkan kiri-kanan
//     1       0      diputar 180 derajat LALU dicerminkan  <-- dipakai sekarang
//
// Keduanya dikerjakan OLEH SENSOR, bukan oleh ESP32 dan bukan oleh sisi
// darat: sensor sekadar membaca larik pikselnya dengan urutan berbeda.
// Jadi benar-benar gratis -- tidak ada tambahan latensi, tidak ada CPU
// terpakai, ukuran JPEG tidak berubah.
#define CAM_VFLIP 0
#define CAM_HMIRROR 0

#define SERIAL_BAUD 115200

// ----------------------------------------------------------------- MJPEG

#define PART_BOUNDARY "rccarframeboundary"

static const char* STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;

// Boundary + header multipart digabung jadi SATU format string (bisa karena
// PART_BOUNDARY adalah literal, disambung compiler saat kompilasi -- beda
// dengan STREAM_BOUNDARY/STREAM_PART_HEADER versi lama yang variabel
// terpisah). Tujuannya supaya keduanya bisa dikirim lewat SATU panggilan
// httpd_resp_send_chunk, bukan dua: dengan TCP_NODELAY aktif tiap panggilan
// cenderung jadi segmen TCP sendiri, jadi menggabungkan boundary (~24 byte)
// dan header (~50 byte) memangkas jumlah paket kecil per frame dari 3 jadi 2
// -- lumayan saat 2-3 kamera streaming bersamaan di 2,4 GHz yang sama.
static const char* STREAM_PART_FORMAT =
    "\r\n--" PART_BOUNDARY "\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static httpd_handle_t server = NULL;
static uint32_t frameCounter = 0;

static const char INDEX_HTML[] PROGMEM =
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>RC Car Camera</title>"
    "<style>body{margin:0;background:#0e0f12;color:#eceff5;"
    "font-family:system-ui,sans-serif;text-align:center}"
    "img{max-width:100%;height:auto;display:block;margin:0 auto}"
    "p{padding:8px;font-size:14px;color:#9aa2b0}</style></head><body>"
    "<img src=\"/stream\" alt=\"stream\">"
    "<p>Kalau gambar tidak muncul, periksa catu daya 5V modul ini.</p>"
    "</body></html>";

// ----------------------------------------------------------------- handler

static esp_err_t indexHandler(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t streamHandler(httpd_req_t* req) {
  esp_err_t result = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  if (result != ESP_OK) {
    return result;
  }
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "X-Framerate", "30");

  // Matikan algoritma Nagle. Tanpa ini, potongan kecil (header tiap frame)
  // ditahan sampai ada data lain yang menyusul, dan video terasa tersendat
  // walaupun jaringannya lega.
  const int sock = httpd_req_to_sockfd(req);
  const int one = 1;
  setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

  Serial.println("[CAM] klien stream tersambung");

  // 128, bukan 64: sekarang menampung boundary + header sekaligus (lihat
  // STREAM_PART_FORMAT di atas), jadi harus lebih longgar dari sebelumnya.
  char partHeader[128];
  while (true) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[CAM] gagal mengambil frame");
      result = ESP_FAIL;
      break;
    }

    if (fb->format != PIXFORMAT_JPEG) {
      // Seharusnya tidak pernah terjadi karena sensor diminta keluar JPEG,
      // tapi kalau terjadi, lebih baik berhenti daripada mengirim sampah.
      esp_camera_fb_return(fb);
      Serial.println("[CAM] format frame bukan JPEG");
      result = ESP_FAIL;
      break;
    }

    const int headerLength =
        snprintf(partHeader, sizeof(partHeader), STREAM_PART_FORMAT, fb->len);

    if (headerLength < 0 || (size_t)headerLength >= sizeof(partHeader)) {
      // Tidak seharusnya terjadi (header jauh di bawah 128 byte), tapi kalau
      // Content-Length suatu saat membengkak, lebih baik putus koneksi
      // daripada mengirim header multipart yang terpotong.
      esp_camera_fb_return(fb);
      Serial.println("[CAM] header multipart melebihi buffer");
      result = ESP_FAIL;
      break;
    }

    result = httpd_resp_send_chunk(req, partHeader, headerLength);
    if (result == ESP_OK) {
      result = httpd_resp_send_chunk(req, (const char*)fb->buf, fb->len);
    }

    esp_camera_fb_return(fb);

    if (result != ESP_OK) {
      // Klien menutup koneksi. Ini normal, bukan kesalahan.
      break;
    }
    frameCounter++;
  }

  Serial.println("[CAM] klien stream terputus");
  return result;
}

static void startServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;
  config.max_open_sockets = 3;
  config.lru_purge_enable = true;

  if (httpd_start(&server, &config) != ESP_OK) {
    Serial.println("[CAM] GAGAL menjalankan server HTTP");
    return;
  }

  httpd_uri_t indexUri = {
      .uri = "/", .method = HTTP_GET, .handler = indexHandler, .user_ctx = NULL};
  httpd_uri_t streamUri = {
      .uri = "/stream", .method = HTTP_GET, .handler = streamHandler, .user_ctx = NULL};

  httpd_register_uri_handler(server, &indexUri);
  httpd_register_uri_handler(server, &streamUri);

  Serial.println("[CAM] server HTTP berjalan di port 80");
}

// ----------------------------------------------------------------- kamera

static bool startCamera() {
  camera_config_t config;
  memset(&config, 0, sizeof(config));

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = CAM_FRAMESIZE;
  config.jpeg_quality = CAM_JPEG_QUALITY;

  // Jalur ini yang dipakai di kedua modul selama PSRAM-nya benar-benar
  // aktif: XIAO ESP32S3 Sense punya PSRAM 8 MB (OPI), AI-Thinker ESP32-CAM
  // punya PSRAM 4 MB (biasa). Untuk XIAO, opsi "PSRAM: OPI PSRAM" WAJIB
  // dipilih di Arduino IDE, kalau tidak psramFound() akan selalu false di
  // sini walau modulnya sebenarnya punya PSRAM.
  if (psramFound()) {
    // 3, bukan 2. Alasannya khusus untuk mode LATEST di bawah, dan hanya
    // terasa saat pengiriman satu frame lewat WiFi memakan waktu lama
    // (sinyal lemah, atau 2-3 kamera berebut 2,4 GHz yang sama):
    //
    // Selama streamHandler menahan satu buffer untuk dikirim, sisa buffer
    // itulah satu-satunya tempat driver menaruh frame baru. Dengan fb_count=2
    // sisanya cuma SATU, jadi begitu buffer itu terisi driver terpaksa
    // berhenti menangkap sampai handler mengembalikan buffernya. Frame yang
    // didapat esp_camera_fb_get() berikutnya karena itu bukan frame terbaru,
    // melainkan frame yang sudah menunggu selama sisa waktu pengiriman.
    //
    // Dengan 3, driver selalu punya dua buffer untuk berputar dan terus
    // menangkap selagi satu frame dikirim -- sehingga LATEST benar-benar
    // memberi frame TERBARU, bukan frame terbaru yang sempat tertangkap
    // sebelum kehabisan buffer. Biayanya hanya satu framebuffer JPEG lagi
    // di PSRAM (XIAO ESP32S3 Sense punya 8 MB; VGA JPEG ~20-40 KB).
    config.fb_count = 3;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    // LATEST, bukan WHEN_EMPTY. Ini yang menentukan apakah video terasa
    // real-time atau tertinggal: dengan LATEST, frame lama yang belum sempat
    // terkirim dibuang, bukan diantrekan. Untuk mengemudi FPV, gambar yang
    // baru selalu lebih berguna daripada gambar yang lengkap tapi telat.
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
    // Tanpa PSRAM, buffer harus muat di RAM internal yang jauh lebih kecil.
    Serial.println("[CAM] PSRAM tidak terdeteksi - turun ke resolusi kecil");
    config.frame_size = FRAMESIZE_QVGA;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  }

  const esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] init kamera GAGAL, kode 0x%x\n", err);
    Serial.println("[CAM] periksa kabel fleksibel kamera dan catu 5V");
    return false;
  }

  sensor_t* sensor = esp_camera_sensor_get();
  if (sensor) {
    // Sedikit dinaikkan: gambar yang agak terang lebih mudah dibaca saat
    // mengemudi di dalam ruangan.
    sensor->set_brightness(sensor, 1);
    sensor->set_saturation(sensor, 0);

    // Orientasi gambar. Tabel kombinasinya ada di dekat CAM_VFLIP di atas.
    // Selalu ditulis ke sensor, termasuk saat nilainya 0, supaya tidak
    // bergantung pada nilai bawaan sensor yang bisa berbeda antar modul.
    sensor->set_vflip(sensor, CAM_VFLIP);
    sensor->set_hmirror(sensor, CAM_HMIRROR);
    Serial.printf("[CAM] orientasi: vflip=%d hmirror=%d\n",
                  CAM_VFLIP, CAM_HMIRROR);
  }
  return true;
}

// ----------------------------------------------------------------- setup

static void startAccessPoint() {
  WiFi.mode(WIFI_AP);

  // Sama seperti varian asli: power save WiFi harus mati, kalau tidak
  // stream tersendat secara acak. Pada mode AP ini bahkan lebih penting --
  // AP yang tidur akan menunda paket ke satu-satunya klien yang ada.
  WiFi.setSleep(false);

  // Alamat AP diterapkan SEBELUM softAP() dijalankan. Kalau dibalik,
  // server DHCP internal sempat menyala dengan subnet bawaan lebih dulu
  // dan klien bisa terlanjur mendapat alamat dari subnet yang salah.
  IPAddress local(CAM_AP_IP_1, CAM_AP_IP_2, CAM_AP_IP_3, CAM_AP_IP_4);
  IPAddress subnet(255, 255, 255, 0);
  if (!WiFi.softAPConfig(local, local, subnet)) {
    Serial.println("[CAM] gagal menerapkan alamat AP, memakai bawaan");
  }

  char ssid[32];
  snprintf(ssid, sizeof(ssid), "%s%d", CAM_AP_SSID_BASE, UNIT_ID);

  const bool ok = WiFi.softAP(
      ssid, CAM_AP_PASS, CAM_AP_CHANNEL, CAM_AP_HIDDEN, CAM_AP_MAX_CLIENTS);

  if (!ok) {
    Serial.println("[CAM] GAGAL menyalakan access point");
    return;
  }

  Serial.printf("[CAM] access point \"%s\" aktif di kanal %d\n",
                ssid, CAM_AP_CHANNEL);
  Serial.print("[CAM] stream di  http://");
  Serial.print(WiFi.softAPIP());
  Serial.println("/stream");
  Serial.println("[CAM] sambungkan LattePanda ke SSID di atas,");
  Serial.println("[CAM] dan ke GL.iNet lewat kabel LAN untuk kendali.");
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  Serial.println();
  Serial.println("=== RC Car ESP32-CAM ===");

  // CATATAN: brownout detector SENGAJA dibiarkan aktif, di kedua modul yang
  // didukung sketch ini.
  //
  // Banyak contoh di internet mematikannya dengan menulis 0 ke
  // RTC_CNTL_BROWN_OUT_REG agar modul berhenti reboot. Itu tidak memperbaiki
  // apa pun -- ia hanya menyembunyikan tegangan yang memang kurang, dan chip
  // tetap berjalan di luar batas amannya. Kalau modul ini reboot, catu
  // dayanya yang harus diperbaiki. Lihat docs/wiring.md.

#if !CAM_BOARD_XIAO_S3
  // Hanya AI-Thinker ESP32-CAM yang punya LED flash di GPIO ini. XIAO
  // ESP32S3 Sense tidak punya LED flash terpisah, jadi LED_FLASH_GPIO_NUM
  // tidak didefinisikan sama sekali untuknya -- jangan setel pin yang tidak
  // ada.
  pinMode(LED_FLASH_GPIO_NUM, OUTPUT);
  digitalWrite(LED_FLASH_GPIO_NUM, LOW);
#endif

  if (!startCamera()) {
    Serial.println("[CAM] berhenti - kamera tidak bisa dipakai");
    while (true) {
      delay(1000);
    }
  }
  Serial.println("[CAM] kamera siap");

  startAccessPoint();
  startServer();
}

void loop() {
  static uint32_t lastReport = 0;
  static uint32_t lastFrames = 0;

  // TIDAK ADA logika sambung-ulang di sini, berbeda dari varian asli.
  // Sebagai AP, kamera tidak pernah "terputus" -- ia yang menyediakan
  // jaringan. Yang datang dan pergi adalah KLIEN, dan itu ditangani
  // sendiri oleh tumpukan WiFi tanpa perlu campur tangan.

  const uint32_t now = millis();
  if (now - lastReport >= 5000) {
    const uint32_t frames = frameCounter - lastFrames;
    lastFrames = frameCounter;
    lastReport = now;
    // RSSI tidak ada artinya di sisi AP (tidak ada satu pun "sinyal yang
    // diterima" milik kita sendiri), jadi diganti jumlah klien yang
    // tersambung -- angka yang benar-benar berguna: 0 berarti LattePanda
    // belum menyambung ke SSID kamera ini.
    Serial.printf("[CAM] %.1f fps | klien %d | heap bebas %u\n",
                  frames / 5.0f, WiFi.softAPgetStationNum(),
                  (unsigned)ESP.getFreeHeap());
  }
  delay(100);
}
