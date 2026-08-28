/*
 * rc_cam_esp32_udp — kamera FPV untuk RC Car, VARIAN UDP.
 *
 * ====================================================================
 * SALINAN TERPISAH. rc_cam_esp32/ dan rc_cam_esp32_ap/ TIDAK diubah dan
 * tetap bisa dipakai kapan saja. Flash yang mana pun untuk membandingkan.
 * ====================================================================
 *
 * MASALAH YANG DIPECAHKAN: video patah-patah.
 *
 * Varian lain mengirim video lewat HTTP di atas TCP. Pada TCP, satu segmen
 * yang hilang menahan SELURUH aliran sampai kiriman ulangnya sampai --
 * video membeku, lalu frame menumpuk datang serentak. Di 2,4 GHz yang
 * padat, paket hilang adalah kejadian normal, bukan kelainan; jadi selama
 * memakai TCP, pembekuan itu tidak bisa dihilangkan, hanya diperjarang
 * dengan memperkecil frame.
 *
 * Varian ini mengirim video lewat UDP. Tidak ada kiriman ulang dan tidak
 * ada jaminan urutan: fragmen yang hilang berarti SATU frame tidak lengkap
 * lalu dibuang sisi darat, dan frame berikutnya tetap datang tepat waktu.
 * Untuk FPV itu pertukaran yang jelas menguntungkan -- gambar hilang
 * sekejap jauh lebih baik daripada seluruh aliran membeku.
 *
 * Ini gagasan inti yang membuat proyek FPV berbasis packet-injection cepat
 * (transport tanpa acknowledgment), tapi DITERAPKAN DI ATAS WiFi BIASA --
 * tanpa mode monitor, tanpa dongle khusus, tanpa ganti OS, dan tanpa
 * menyentuh tautan kendali 50 Hz yang sudah bekerja.
 *
 * PROTOKOL: lihat docs/protocol.md bagian 8. Kembar dengan
 * ground/rcground/protocol.py -- kalau salah satu diubah, ubah ketiganya.
 *
 *   Fragmen video  kamera -> darat, port 4211, header 10 byte:
 *     'R','V', versi, unit_id, frame_id(u16), index(u8), count(u8), len(u16)
 *
 *   Subscribe      darat -> kamera, port 4211, 4 byte:
 *     'R','S', versi, unit_id
 *
 * Sisi darat mengirim subscribe BERKALA, bukan sekali. Kamera berhenti
 * mengirim kalau permintaan berhenti datang. Itu penting justru karena UDP
 * tidak punya backpressure seperti TCP: tanpa ini, kamera yang ditinggalkan
 * akan terus membanjiri jaringan dan mengganggu paket kendali mobil lain.
 *
 * SERVER HTTP TETAP ADA. Buka http://<ip-kamera>/ di browser untuk
 * memastikan kamera hidup dan gambarnya benar, tanpa perlu menjalankan
 * aplikasi darat. Yang dipakai untuk mengemudi adalah jalur UDP.
 *
 * CARA MEMAKAI DI SISI DARAT:
 *   Di ground/config.yaml, di blok camera:, isi
 *     transport: udp
 *   Alamat kamera tetap diturunkan dari unit: seperti biasa.
 *
 * Board dan cara flash sama persis dengan varian lain -- lihat
 * rc_cam_esp32/rc_cam_esp32.ino.
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <lwip/sockets.h>

#include "camera_pins.h"
#include "esp_camera.h"
#include "esp_http_server.h"

// ----------------------------------------------------------------- setelan

// =================================================================
// UNIT_ID -- HARUS SAMA dengan UNIT_ID di firmware/rc_car_esp32/config.h
// milik mobil yang sama, dan dengan unit: di ground/config.yaml.
// Sisi darat membuang fragmen dari unit lain sebelum ikut membentuk
// frame, jadi unit yang salah = tidak ada video sama sekali.
// =================================================================
#define UNIT_ID 3

#define WIFI_SSID "RCCar"
#define WIFI_PASS "admin.admin"

#define CAM_IP_1 192
#define CAM_IP_2 168
#define CAM_IP_3 8
#define CAM_IP_4 (59 + UNIT_ID)
#define GATEWAY_IP_4 1
#define USE_DHCP 0

// ------------------------------------------------------------ protokol UDP

#define VIDEO_PORT 4211
#define PROTOCOL_VERSION 3

// Muatan maksimum per fragmen. 1400 + 10 byte header = 1410, aman di bawah
// MTU 1500 dikurangi header IP (20) dan UDP (8) = 1472. Sengaja tidak
// dipepet: kalau satu datagram sampai terpecah di lapisan IP, hilangnya
// SATU fragmen IP membuang seluruh datagram -- persis yang ingin dihindari.
#define VIDEO_PAYLOAD_MAX 1400
#define VIDEO_HEADER_SIZE 10

// Berhenti mengirim kalau tidak ada permintaan subscribe selama ini.
// Lihat catatan backpressure di header berkas.
#define SUBSCRIBE_TIMEOUT_MS 3000

// Jeda antar fragmen dalam satu frame, mikrodetik. 0 = kirim secepatnya.
//
// KENAPA INI ADA: UDP tidak punya kendali aliran. Mengirim 20 fragmen
// secepat mungkin membuat ledakan yang bisa meluapkan buffer penerima dan
// merebut airtime dari paket kendali 50 Hz. Jeda kecil menyebarkan
// ledakan itu tanpa terasa menambah latensi.
//
// Naikkan kalau paket kendali ikut tersendat saat video mengalir; turunkan
// ke 0 kalau jaringan lega dan ingin latensi seminimal mungkin.
#define FRAGMENT_GAP_US 200

// ----------------------------------------------------------------- kamera

#define CAM_FRAMESIZE FRAMESIZE_VGA
#define CAM_JPEG_QUALITY 20
#define CAM_VFLIP 0
#define CAM_HMIRROR 0

#define SERIAL_BAUD 115200

// ----------------------------------------------------------------- global

static httpd_handle_t server = NULL;
static WiFiUDP udp;
static uint32_t frameCounter = 0;
static uint32_t droppedFrames = 0;
static uint16_t frameId = 0;

static IPAddress subscriberIp;
static uint16_t subscriberPort = 0;
static uint32_t lastSubscribeMs = 0;

static const char INDEX_HTML[] PROGMEM =
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>RC Car Camera (UDP)</title>"
    "<style>body{margin:0;background:#0e0f12;color:#eceff5;"
    "font-family:system-ui,sans-serif;text-align:center;padding:24px}"
    "p{font-size:14px;color:#9aa2b0}</style></head><body>"
    "<h2>Kamera UDP aktif</h2>"
    "<p>Varian ini mengirim video lewat UDP ke aplikasi darat, bukan lewat "
    "halaman ini. Kalau halaman ini terbuka, kamera dan WiFi-nya sehat.</p>"
    "<p>Setel <code>transport: udp</code> di ground/config.yaml.</p>"
    "</body></html>";

// ----------------------------------------------------------------- handler

static esp_err_t indexHandler(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
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
  httpd_register_uri_handler(server, &indexUri);
  Serial.println("[CAM] server HTTP berjalan di port 80 (halaman status saja)");
}

// ----------------------------------------------------------------- UDP

static void pollSubscribers() {
  const int size = udp.parsePacket();
  if (size <= 0) {
    return;
  }
  uint8_t buffer[8];
  const int read = udp.read(buffer, sizeof(buffer));
  if (read != 4) {
    return;
  }
  // 'R','S', versi, unit_id -- paket lain dibuang tanpa efek, aturan yang
  // sama dengan paket kendali cacat di firmware mobil.
  if (buffer[0] != 'R' || buffer[1] != 'S') {
    return;
  }
  if (buffer[2] != PROTOCOL_VERSION || buffer[3] != UNIT_ID) {
    return;
  }

  const IPAddress from = udp.remoteIP();
  const uint16_t port = udp.remotePort();
  if (from != subscriberIp || port != subscriberPort) {
    Serial.print("[CAM] pelanggan baru: ");
    Serial.print(from);
    Serial.printf(":%u\n", port);
  }
  subscriberIp = from;
  subscriberPort = port;
  lastSubscribeMs = millis();
}

static bool hasSubscriber() {
  if (subscriberPort == 0) {
    return false;
  }
  return (millis() - lastSubscribeMs) <= SUBSCRIBE_TIMEOUT_MS;
}

/* Kirim satu frame JPEG sebagai deretan fragmen UDP.
 *
 * Kegagalan mengirim satu fragmen TIDAK menghentikan sisanya: sisi darat
 * memang dirancang membuang frame yang tidak lengkap, jadi menyerah di
 * tengah hanya membuang frame yang sama sambil menambah percabangan. */
static bool sendFrame(const uint8_t* data, size_t length) {
  const uint8_t count =
      (uint8_t)((length + VIDEO_PAYLOAD_MAX - 1) / VIDEO_PAYLOAD_MAX);
  if (count == 0) {
    return false;
  }

  uint8_t header[VIDEO_HEADER_SIZE];
  header[0] = 'R';
  header[1] = 'V';
  header[2] = PROTOCOL_VERSION;
  header[3] = UNIT_ID;
  header[4] = (uint8_t)(frameId & 0xFF);          // little-endian, u16
  header[5] = (uint8_t)((frameId >> 8) & 0xFF);
  header[7] = count;

  bool ok = true;
  for (uint8_t index = 0; index < count; index++) {
    const size_t offset = (size_t)index * VIDEO_PAYLOAD_MAX;
    const size_t chunk =
        (length - offset) > VIDEO_PAYLOAD_MAX ? VIDEO_PAYLOAD_MAX : (length - offset);

    header[6] = index;
    header[8] = (uint8_t)(chunk & 0xFF);          // little-endian, u16
    header[9] = (uint8_t)((chunk >> 8) & 0xFF);

    if (!udp.beginPacket(subscriberIp, subscriberPort)) {
      ok = false;
      continue;
    }
    udp.write(header, VIDEO_HEADER_SIZE);
    udp.write(data + offset, chunk);
    if (udp.endPacket() != 1) {
      ok = false;
    }

#if FRAGMENT_GAP_US > 0
    if (index + 1 < count) {
      delayMicroseconds(FRAGMENT_GAP_US);
    }
#endif
  }

  frameId++;
  return ok;
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

  if (psramFound()) {
    config.fb_count = 3;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
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
    sensor->set_brightness(sensor, 1);
    sensor->set_saturation(sensor, 0);
    sensor->set_vflip(sensor, CAM_VFLIP);
    sensor->set_hmirror(sensor, CAM_HMIRROR);
  }
  return true;
}

// ----------------------------------------------------------------- setup

static void connectWifi() {
  WiFi.mode(WIFI_STA);
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

  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < 20000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[CAM] tersambung di ");
    Serial.println(WiFi.localIP());
    Serial.printf("[CAM] menunggu subscribe UDP di port %d\n", VIDEO_PORT);
  } else {
    Serial.println("[CAM] gagal menyambung - akan terus mencoba di loop()");
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  Serial.println();
  Serial.println("=== RC Car ESP32-CAM (UDP) ===");

#if !CAM_BOARD_XIAO_S3
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
  udp.begin(VIDEO_PORT);
  startServer();
}

void loop() {
  static uint32_t lastReport = 0;
  static uint32_t lastFrames = 0;

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[CAM] WiFi terputus, menyambung ulang...");
    WiFi.reconnect();
    delay(8000);
    return;
  }

  pollSubscribers();

  // Tanpa pelanggan, JANGAN mengambil frame sama sekali. Ini bukan sekadar
  // hemat: mengambil frame yang tidak akan dikirim tetap memakan CPU dan
  // membuat sensor bekerja penuh tanpa guna.
  if (hasSubscriber()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) {
      if (fb->format == PIXFORMAT_JPEG) {
        if (sendFrame(fb->buf, fb->len)) {
          frameCounter++;
        } else {
          droppedFrames++;
        }
      }
      esp_camera_fb_return(fb);
    }
  } else {
    delay(20);
  }

  const uint32_t now = millis();
  if (now - lastReport >= 5000) {
    const uint32_t frames = frameCounter - lastFrames;
    lastFrames = frameCounter;
    lastReport = now;
    Serial.printf("[CAM] %.1f fps | pelanggan %s | gagal-kirim %u | rssi %d | heap %u\n",
                  frames / 5.0f, hasSubscriber() ? "ya" : "TIDAK",
                  (unsigned)droppedFrames, WiFi.RSSI(),
                  (unsigned)ESP.getFreeHeap());
  }
}
