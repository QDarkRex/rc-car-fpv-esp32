"""Pembaca stream MJPEG dari ESP32-CAM.

Ditulis manual, bukan lewat pembaca video umum, karena satu alasan spesifik:
pembaca yang mem-buffer akan menumpuk frame lama saat jaringan tersendat, dan
video jadi tertinggal beberapa detik dari kenyataan. Untuk mengemudi FPV itu
fatal. Di sini hanya SATU frame terbaru yang disimpan; frame lama yang belum
sempat digambar langsung dibuang.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from collections import deque

SOI = b"\xff\xd8"   # penanda awal JPEG
EOI = b"\xff\xd9"   # penanda akhir JPEG
MAX_FRAME_BYTES = 1024 * 1024


class MjpegStream:
    """Menarik stream MJPEG di thread terpisah, menyimpan frame terbaru saja."""

    def __init__(self, url: str, timeout: float = 3.0) -> None:
        self.url = url
        self.timeout = timeout

        self._lock = threading.Lock()
        self._frame: bytes | None = None
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

    @property
    def fps(self) -> float:
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._frame_times if now - t <= 2.0]
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return 0.0 if span <= 0 else (len(times) - 1) / span

    # -- internal --------------------------------------------------------
    def _publish(self, jpeg: bytes) -> None:
        with self._lock:
            self._frame = jpeg
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
            chunk = response.read(4096)
            if not chunk:
                return
            buffer.extend(chunk)

            # Ambil setiap JPEG utuh yang sudah lengkap di dalam buffer.
            # Pencarian SOI/EOI dipakai alih-alih parsing boundary karena tahan
            # terhadap variasi format header antar firmware kamera.
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
                self._publish(bytes(buffer[start:end]))
                del buffer[:end]
