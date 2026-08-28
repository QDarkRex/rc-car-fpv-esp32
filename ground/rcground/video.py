"""Pembaca stream MJPEG dari ESP32-CAM.

Ditulis manual, bukan lewat pembaca video umum, karena satu alasan spesifik:
pembaca yang mem-buffer akan menumpuk frame lama saat jaringan tersendat, dan
video jadi tertinggal beberapa detik dari kenyataan. Untuk mengemudi FPV itu
fatal. Di sini hanya SATU frame terbaru yang disimpan; frame lama yang belum
sempat digambar langsung dibuang.

Sumber latensi lain yang sudah ditutup: pembacaan socket memakai read1(),
bukan read(), karena pada HTTPResponse chunked read(n) menunggu genap n byte
sehingga menahan ekor tiap frame sampai frame berikutnya datang (lihat
komentar di _read_stream()).

Sumber ketiga, ditutup dengan decode=True: dekode JPEG dulu dikerjakan di
loop kendali 50 Hz sisi darat. Dekode VGA memakan 8-20 ms di CPU lemah
(LattePanda), dan itu masuk DUA KALI ke dalam masalah -- menunda gambar
tampil, sekaligus memakan jatah waktu loop yang seharusnya dipakai mengirim
paket kendali. Dengan decode=True, thread ini yang mendekode, dan loop utama
tinggal memakai Surface yang sudah jadi. Lihat _publish().
"""

from __future__ import annotations

import io
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

import pygame

from . import protocol as proto

SOI = b"\xff\xd8"   # penanda awal JPEG
EOI = b"\xff\xd9"   # penanda akhir JPEG
MAX_FRAME_BYTES = 1024 * 1024

# Timeout recvfrom() di penerima UDP. Cukup pendek supaya thread bisa
# memeriksa flag berhenti dan menandai tautan mati dengan wajar, cukup
# panjang supaya tidak berputar sia-sia saat kamera memang diam.
RECV_TIMEOUT = 0.2


def decode_jpeg(jpeg: bytes) -> "pygame.Surface | None":
    """Dekode satu frame. None kalau frame rusak -- bukan alasan berhenti.

    Dipakai oleh KEDUA penerima (HTTP dan UDP), selalu dari thread jaringan
    masing-masing, tidak pernah dari loop kendali 50 Hz.

    pygame.image.load() memakai SDL_image dan tidak menyentuh display, jadi
    aman dipanggil dari thread. Yang TIDAK aman adalah Surface.convert();
    itu ditinggalkan untuk thread utama.
    """
    try:
        return pygame.image.load(io.BytesIO(jpeg), "frame.jpg")
    except (pygame.error, ValueError):
        return None


class CameraPing:
    """Ukur bolak-balik jaringan ke modul kamera, terpisah dari stream-nya.

    Kenapa TCP connect, bukan ICMP: ping ICMP di Windows butuh socket raw
    (hak administrator) atau memanggil ping.exe lalu mengurai keluarannya --
    dan keluaran itu berbeda-beda mengikuti bahasa Windows, jadi rapuh.
    Membuka koneksi TCP ke port HTTP kamera lalu langsung menutupnya memberi
    angka yang presisi, tanpa hak khusus, tanpa proses tambahan, dan tanpa
    bergantung bahasa.

    Yang diukur karena itu bukan sekadar jalur radionya, melainkan sampai ke
    server HTTP kamera -- justru lebih relevan untuk kesehatan video,
    karena modul itulah yang sedang sibuk mengirim frame.

    SOAL BATAS SOCKET: firmware kamera memakai max_open_sockets = 3 dengan
    lru_purge_enable. Stream memakai satu, probe ini memakai satu lagi
    sesaat, jadi paling banyak dua dari tiga -- selalu tersisa satu slot.
    JANGAN memperpendek interval sampai probe menumpuk; kalau slot habis,
    LRU purge bisa memutus koneksi stream yang sedang berjalan.
    """

    def __init__(self, url: str, interval: float = 2.0, timeout: float = 1.5) -> None:
        parsed = urllib.parse.urlparse(url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.interval = max(0.5, float(interval))
        self.timeout = float(timeout)

        self._lock = threading.Lock()
        self._window: deque = deque(maxlen=5)
        self._rtt_ms: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="camping", daemon=True
        )

    def start(self) -> "CameraPing":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    @property
    def rtt_ms(self) -> float | None:
        """Rata-rata bolak-balik terakhir, None kalau kamera tidak menjawab."""
        with self._lock:
            return self._rtt_ms

    def _probe(self) -> float | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        started = time.monotonic()
        try:
            sock.connect((self.host, self.port))
            return (time.monotonic() - started) * 1000.0
        except OSError:
            return None
        finally:
            try:
                # Ditutup dengan segera supaya slot socket di kamera langsung
                # bebas lagi -- lihat catatan batas socket di docstring kelas.
                sock.close()
            except OSError:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            rtt = self._probe()
            with self._lock:
                if rtt is None:
                    # Satu kegagalan belum tentu berarti kamera hilang, tapi
                    # angka lama juga tidak boleh dipajang seolah masih sahih.
                    self._window.clear()
                    self._rtt_ms = None
                else:
                    self._window.append(rtt)
                    self._rtt_ms = sum(self._window) / len(self._window)
            self._stop.wait(self.interval)


class UdpVideoStream:
    """Penerima video UDP -- pengganti MjpegStream saat memakai firmware UDP.

    Antarmukanya SENGAJA sama persis dengan MjpegStream (latest,
    latest_surface, fps, worst_gap_ms, connected, error, stop) supaya
    main.py, HUD, dan latency_test.py tidak perlu tahu yang mana yang
    sedang dipakai.

    Kenapa ada: pada HTTP/TCP, satu segmen hilang menahan SELURUH aliran
    sampai kiriman ulangnya sampai -- video membeku lalu frame menumpuk
    datang serentak. Di sini fragmen yang hilang hanya membuang SATU frame;
    frame berikutnya tetap datang tepat waktu. Lihat catatan panjang di
    rcground/protocol.py bagian video UDP.

    Frame yang tidak lengkap dibuang tanpa upaya penyelamatan apa pun.
    Menampilkan JPEG yang separuh datanya hilang hanya menghasilkan sampah,
    dan frame berikutnya toh tinggal beberapa puluh milidetik lagi.
    """

    def __init__(
        self,
        unit_id: int,
        camera_host: str,
        port: int = proto.VIDEO_PORT,
        decode: bool = False,
        subscribe_interval: float = 1.0,
    ) -> None:
        self.unit_id = int(unit_id)
        self.camera_addr = (str(camera_host), int(port))
        self.subscribe_interval = float(subscribe_interval)
        self._decode = decode

        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._surface: "pygame.Surface | None" = None
        self._frame_id = 0
        self._frame_times: deque = deque(maxlen=60)

        # Perakitan ulang fragmen. Hanya beberapa frame terakhir yang
        # disimpan: frame yang lebih tua dari yang sudah selesai tidak
        # mungkin berguna lagi, dan menyimpannya hanya membuang memori.
        self._pending: dict = {}
        self._newest_done = -1

        self.connected = False
        self.error: str | None = None
        self.reconnects = 0
        # Fragmen yang tiba untuk frame yang keburu dibuang, atau frame yang
        # tidak pernah lengkap. Berguna untuk membedakan "jaringan buruk"
        # dari "kamera tidak mengirim".
        self.dropped_frames = 0

        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._rx_thread = threading.Thread(
            target=self._rx_loop, name="udpvideo", daemon=True
        )
        self._tx_thread = threading.Thread(
            target=self._subscribe_loop, name="udpsub", daemon=True
        )

    # -- siklus hidup ----------------------------------------------------
    def start(self) -> "UdpVideoStream":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Buffer terima diperbesar: satu frame VGA bisa 20+ fragmen yang tiba
        # nyaris bersamaan, dan buffer bawaan OS bisa meluap justru pada
        # ledakan seperti itu -- yang akan terlihat sebagai frame tidak
        # lengkap padahal jaringannya sehat.
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass
        self._sock.bind(("0.0.0.0", 0))
        self._sock.settimeout(RECV_TIMEOUT)
        self._rx_thread.start()
        self._tx_thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    # -- akses frame (sama seperti MjpegStream) --------------------------
    def latest(self) -> tuple:
        with self._lock:
            return self._frame, self._frame_id

    def latest_surface(self) -> tuple:
        with self._lock:
            return self._surface, self._frame_id

    @property
    def fps(self) -> float:
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._frame_times if now - t <= 2.0]
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return 0.0 if span <= 0 else (len(times) - 1) / span

    @property
    def worst_gap_ms(self) -> float:
        """Jeda terpanjang antar frame -- lihat MjpegStream.worst_gap_ms."""
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._frame_times if now - t <= 3.0]
        if not times:
            return 0.0
        gaps = [
            (later - earlier) * 1000.0
            for earlier, later in zip(times, times[1:])
        ]
        gaps.append((now - times[-1]) * 1000.0)
        return max(gaps)

    # -- internal --------------------------------------------------------
    def _subscribe_loop(self) -> None:
        """Minta kamera mengirim, berkala.

        Berkala, bukan sekali: kalau aplikasi darat mati mendadak, kamera
        berhenti sendiri setelah permintaan berhenti datang. UDP tidak punya
        backpressure -- tanpa ini, kamera yang ditinggalkan akan terus
        membanjiri jaringan dan mengganggu paket kendali mobil lain.
        """
        packet = proto.pack_subscribe(self.unit_id)
        while not self._stop.is_set():
            try:
                if self._sock is not None:
                    self._sock.sendto(packet, self.camera_addr)
            except OSError as exc:
                self.error = str(exc)
            self._stop.wait(self.subscribe_interval)

    def _publish(self, jpeg: bytes) -> None:
        # Dekode di luar lock, alasan sama seperti MjpegStream._publish.
        surface = decode_jpeg(jpeg) if self._decode else None
        with self._lock:
            self._frame = jpeg
            self._surface = surface
            self._frame_id += 1
            self._frame_times.append(time.monotonic())

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(2048)
            except (TimeoutError, socket.timeout):
                # Tidak ada frame dalam RECV_TIMEOUT. Bukan kesalahan --
                # kamera mungkin baru menyala. connected dievaluasi dari
                # waktu frame terakhir, bukan dari sini.
                self._expire()
                continue
            except OSError:
                return

            fragment = proto.parse_video(data)
            if fragment is None:
                continue
            if fragment.unit_id != self.unit_id:
                # Kamera unit lain terdengar. Dibuang SEBELUM ikut membentuk
                # frame -- alasan yang sama dengan penyaringan unit_id di
                # link.py: lebih baik tidak ada video daripada video mobil
                # sebelah. Lihat docs/protocol.md bagian 7.
                continue

            self._accept(fragment)

    def _accept(self, fragment) -> None:
        frame_id = fragment.frame_id
        # Frame yang lebih tua dari yang sudah selesai tidak berguna lagi.
        # Perbandingan memakai selisih bertanda supaya pembungkusan di 65535
        # tidak membuat frame baru terlihat "lebih tua".
        if self._newest_done >= 0:
            age = (self._newest_done - frame_id) & 0xFFFF
            if 0 < age < 0x8000:
                return

        slot = self._pending.get(frame_id)
        if slot is None:
            slot = {"count": fragment.count, "parts": {}}
            self._pending[frame_id] = slot
        slot["parts"][fragment.index] = fragment.payload

        if len(slot["parts"]) != slot["count"]:
            self._prune()
            return

        jpeg = b"".join(slot["parts"][i] for i in range(slot["count"]))
        del self._pending[frame_id]
        self._newest_done = frame_id
        self.connected = True
        self.error = None
        # Semua frame yang masih menunggu dan lebih tua dari ini tidak akan
        # pernah lengkap lagi -- fragmennya sudah lewat.
        for older in [
            fid for fid in self._pending
            if 0 < ((frame_id - fid) & 0xFFFF) < 0x8000
        ]:
            del self._pending[older]
            self.dropped_frames += 1
        self._publish(jpeg)

    def _prune(self) -> None:
        # Batas keras supaya frame yang tidak pernah lengkap tidak menumpuk.
        while len(self._pending) > 8:
            oldest = min(self._pending)
            del self._pending[oldest]
            self.dropped_frames += 1

    def _expire(self) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._frame_times[-1] if self._frame_times else 0.0
        if last and (now - last) > 2.0:
            self.connected = False
            self.error = "tidak ada frame dari kamera"


class MjpegStream:
    """Menarik stream MJPEG di thread terpisah, menyimpan frame terbaru saja."""

    def __init__(self, url: str, timeout: float = 3.0, decode: bool = False) -> None:
        self.url = url
        self.timeout = timeout
        # decode=False mempertahankan perilaku lama (hanya menyimpan byte
        # JPEG) supaya pemakai lain -- termasuk test parser -- tidak menyentuh
        # pygame sama sekali. main.py menyalakannya; lihat catatan di docstring.
        self._decode = decode

        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._surface: "pygame.Surface | None" = None
        self._frame_id = 0
        self._stop = threading.Event()
        self._frame_times: deque = deque(maxlen=60)

        self.connected = False
        self.error: str | None = None
        self.reconnects = 0

        self._thread = threading.Thread(target=self._run, name="mjpeg", daemon=True)

    # -- siklus hidup ----------------------------------------------------
    def start(self) -> "MjpegStream":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    # -- akses frame -----------------------------------------------------
    def latest(self) -> tuple:
        """Kembalikan (bytes_jpeg, frame_id). frame_id naik tiap frame baru."""
        with self._lock:
            return self._frame, self._frame_id

    def latest_surface(self) -> tuple:
        """Kembalikan (Surface_belum_convert, frame_id) hasil dekode thread ini.

        Surface-nya sengaja BELUM di-convert(): convert() menyalin ke format
        piksel layar dan karena itu butuh display yang sudah ada, jadi ia
        milik thread utama. Yang mahal -- dekode JPEG -- sudah selesai di
        sini. Kembalikan (None, id) kalau decode dimatikan atau frame itu
        gagal didekode; pemanggil lalu boleh jatuh kembali ke latest().
        """
        with self._lock:
            return self._surface, self._frame_id

    @property
    def fps(self) -> float:
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._frame_times if now - t <= 2.0]
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return 0.0 if span <= 0 else (len(times) - 1) / span

    @property
    def worst_gap_ms(self) -> float:
        """Jeda TERPANJANG antar frame dalam 3 detik terakhir, milidetik.

        Inilah angka yang mewakili rasa "patah-patah", dan sengaja dipisah
        dari fps karena fps TIDAK BISA menunjukkannya: fps adalah rata-rata,
        jadi beku 400 ms lalu menyusul dengan kiriman beruntun tetap terbaca
        sekitar 20 fps. Yang dirasakan mata justru bekunya, bukan rata-ratanya.

        Pada 20 fps yang mulus, angka ini sekitar 50 ms. Angka beberapa ratus
        milidetik berarti aliran benar-benar terhenti sejenak -- pada video
        lewat TCP, penyebab paling lazimnya adalah satu paket hilang yang
        menahan seluruh aliran sampai kiriman ulangnya berhasil.

        Jeda sejak frame TERAKHIR ikut dihitung, supaya pembekuan yang sedang
        BERLANGSUNG terlihat saat itu juga, bukan baru muncul setelah selesai.
        """
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._frame_times if now - t <= 3.0]
        if not times:
            return 0.0
        gaps = [
            (later - earlier) * 1000.0
            for earlier, later in zip(times, times[1:])
        ]
        gaps.append((now - times[-1]) * 1000.0)
        return max(gaps)

    # -- internal --------------------------------------------------------
    def _publish(self, jpeg: bytes) -> None:
        # Dekode DI LUAR lock: menahan lock selama belasan milidetik akan
        # memblokir latest()/latest_surface() di loop utama, dan itu persis
        # jenis jeda yang thread ini ada untuk mencegahnya.
        surface = decode_jpeg(jpeg) if self._decode else None
        with self._lock:
            self._frame = jpeg
            self._surface = surface
            self._frame_id += 1
            self._frame_times.append(time.monotonic())

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            try:
                request = urllib.request.Request(
                    self.url, headers={"Connection": "close"}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.connected = True
                    self.error = None
                    backoff = 0.5
                    self._read_stream(response)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self.error = str(exc)
            except Exception as exc:  # noqa: BLE001 - thread tidak boleh mati diam-diam
                self.error = f"{type(exc).__name__}: {exc}"

            self.connected = False
            if self._stop.is_set():
                return
            self.reconnects += 1
            # Backoff bertahap supaya tidak membanjiri kamera yang sedang boot.
            self._stop.wait(backoff)
            backoff = min(backoff * 2.0, 4.0)

    def _read_stream(self, response) -> None:
        """Baca badan multipart/x-mixed-replace, satu bagian per frame."""
        buffer = bytearray()

        while not self._stop.is_set():
            # WAJIB read1(), BUKAN read(). response ini HTTPResponse chunked
            # (esp_http_server firmware kamera pakai Transfer-Encoding: chunked).
            # read(n) pada mode chunked memanggil _read_chunked(n) yang MENUNGGU
            # sampai genap n byte terkumpul, melintasi batas chunk -- akibatnya
            # ekor tiap frame (sisa < 4096 byte) tertahan di dalam http.client
            # sampai data frame BERIKUTNYA mulai datang untuk menggenapinya.
            # Diukur langsung (server chunked tiruan, frame 20 KB @ 10 fps):
            # read(4096) -> lag 101 ms/frame (persis satu periode frame) dan
            # frame terakhir tidak pernah terlihat sama sekali; read1(65536)
            # -> lag 0,1 ms/frame, semua frame terlihat. read1() memanggil
            # _read1_chunked(n) yang mengembalikan apa pun yang SUDAH tersedia
            # tanpa menunggu genap n byte -- JANGAN "rapikan" ini balik ke read().
            chunk = response.read1(65536)
            if not chunk:
                return
            buffer.extend(chunk)

            # Ambil frame utuh yang sudah lengkap di dalam buffer. Bila satu
            # read1() membawa beberapa frame, hanya frame terakhir yang
            # dipublikasikan; frame lama dibuang sebelum UI mendekode.
            # Pencarian SOI/EOI dipakai alih-alih parsing boundary karena tahan
            # terhadap variasi format header antar firmware kamera.
            newest: bytes | None = None
            while True:
                start = buffer.find(SOI)
                if start < 0:
                    if len(buffer) > MAX_FRAME_BYTES:
                        del buffer[:-2]
                    break
                end = buffer.find(EOI, start + 2)
                if end < 0:
                    if start > 0:
                        del buffer[:start]
                    if len(buffer) > MAX_FRAME_BYTES:
                        buffer.clear()
                    break

                end += 2
                newest = bytes(buffer[start:end])
                del buffer[:end]
            if newest is not None:
                self._publish(newest)
