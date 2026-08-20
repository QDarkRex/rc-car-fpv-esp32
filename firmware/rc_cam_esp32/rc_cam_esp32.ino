/*
 * rc_cam_esp32 — kamera FPV untuk RC Car.
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
 * Endpoint:
 *   http://192.168.137.60/         halaman pratinjau sederhana
 *   http://192.168.137.60/stream   stream MJPEG yang dipakai ground station
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

#define WIFI_SSID "RCCar"
#define WIFI_PASS "admin.admin"

// Harus sama dengan camera.stream_url di ground/config.yaml
#define CAM_IP_1 192
#define CAM_IP_2 168
#define CAM_IP_3 137
#define CAM_IP_4 60
#define GATEWAY_IP_4 1
#define USE_DHCP 0

// FRAMESIZE_VGA (640x480) adalah titik seimbang yang baik untuk mengemudi.
// Naik ke SVGA/XGA menambah detail tapi juga menambah latensi dan membuat
// stream lebih rapuh saat sinyal melemah. Turun ke QVGA kalau jangkauan
// lebih penting daripada ketajaman.
#define CAM_FRAMESIZE FRAMESIZE_VGA

// 10 = kualitas terbaik, 63 = terburuk. Angka lebih besar = frame lebih kecil
// = lebih tahan terhadap sinyal lemah.
#define CAM_JPEG_QUALITY 12

#define SERIAL_BAUD 115200

// ----------------------------------------------------------------- MJPEG

#define PART_BOUNDARY "rccarframeboundary"

static const char* STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* STREAM_PART_HEADER =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

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

  char partHeader[64];
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

    const size_t headerLength =
        snprintf(partHeader, sizeof(partHeader), STREAM_PART_HEADER, fb->len);

    result = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (result == ESP_OK) {
      result = httpd_resp_send_chunk(req, partHeader, headerLength);
    }
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
    config.fb_count = 2;
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
    // Balik gambar kalau kamera Anda terpasang terbalik di sasis.
    // sensor->set_vflip(sensor, 1);
    // sensor->set_hmirror(sensor, 1);
  }
  return true;
}

// ----------------------------------------------------------------- setup

static void connectWifi() {
  WiFi.mode(WIFI_STA);

  // Sama seperti di firmware mobil: power save WiFi harus mati, kalau tidak
  // stream tersendat secara acak.
  WiFi.setSleep(false);

#if !USE_DHCP
  IPAddress local(CAM_IP_1, CAM_IP_2, CAM_IP_3, CAM_IP_4);
  IPAddress gateway(CAM_IP_1, CAM_IP_2, CAM_IP_3, GATEWAY_IP_4);
  IPAddress subnet(255, 255, 255, 0);
  if (!WiFi.config(local, gateway, subnet, gateway)) {
    Serial.println("[CAM] gagal menerapkan IP statis, memakai DHCP");
  }
#endif

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[CAM] menyambung ke \"%s\"", WIFI_SSID);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < 20000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[CAM] tersambung. Stream di  http://");
    Serial.print(WiFi.localIP());
    Serial.println("/stream");
  } else {
    Serial.println("[CAM] gagal menyambung - akan terus mencoba di loop()");
  }
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

  connectWifi();
  startServer();
}

void loop() {
  static uint32_t lastReport = 0;
  static uint32_t lastFrames = 0;

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[CAM] WiFi terputus, menyambung ulang...");
    WiFi.reconnect();
    delay(1000);
    return;
  }

  const uint32_t now = millis();
  if (now - lastReport >= 5000) {
    const uint32_t frames = frameCounter - lastFrames;
    lastFrames = frameCounter;
    lastReport = now;
    Serial.printf("[CAM] %.1f fps | rssi %d dBm | heap bebas %u\n",
                  frames / 5.0f, WiFi.RSSI(), (unsigned)ESP.getFreeHeap());
  }
  delay(100);
}
