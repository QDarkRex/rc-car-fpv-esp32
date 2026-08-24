"""Tautan UDP ke mobil: pengiriman kendali, penerimaan telemetri, dan RTT.

Mobil memakai IP statis, jadi normalnya paket dikirim unicast langsung.
Selama telemetri belum pernah diterima, paket juga dikirim ke alamat broadcast
sebagai cadangan bila subnet ternyata berbeda. Selama fase itu tautan dianggap
BELUM terkunci dan arming tidak diizinkan -- lihat docs/protocol.md bagian 6.

Dengan 3 mobil di satu jaringan, broadcast discovery TETAP aman berkat
unit_id di protokol v3: setiap paket kontrol membawa unit_id pengirim,
mobil membuang paket yang bukan untuknya, dan sebaliknya ground station ini
membuang telemetri dari unit_id lain SEBELUM locked_addr sempat terkunci ke
alamat itu. Tanpa penyaringan ini, ground station unit 1 bisa mengunci ke
mobil unit 2 kalau mobil unit 2 kebetulan membalas lebih dulu -- berbahaya
saat balapan. Lihat docs/protocol.md bagian 7.

Penerimaan berjalan di thread sendiri. Ini bukan sekadar rapi: kalau telemetri
baru dibaca saat loop render kebetulan sempat, waktu tibanya ikut terkena
jadwal render dan angka RTT di HUD menjadi salah -- terbaca puluhan milidetik
padahal jaringannya sehat. Thread ini mencatat waktu tiba begitu paket sampai.
"""

from __future__ import annotations

import socket
import threading
import time
from collections import deque

from . import protocol as proto

RECV_TIMEOUT = 0.2


class Link:
    def __init__(self, config: dict) -> None:
        net = config.get("network", {})
        # unit_id milik ground station INI -- setiap paket kontrol yang
        # dikirim membawa nomor ini, dan setiap telemetri yang unit_id-nya
        # berbeda dibuang. Lihat docs/protocol.md bagian 7 dan TUGAS 3 di
        # config.yaml untuk cara menurunkannya dari kunci `unit:`.
        self.unit_id = int(config.get("unit", 1))
        self.car_addr = (
            str(net.get("car_ip", "192.168.137.50")),
            int(net.get("car_port", proto.CONTROL_PORT)),
        )
        self.broadcast_addr = (
            str(net.get("broadcast", "255.255.255.255")),
            int(net.get("car_port", proto.CONTROL_PORT)),
        )
        self.timeout = float(net.get("link_timeout_ms", 500)) / 1000.0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(RECV_TIMEOUT)

        self._lock = threading.Lock()
        self._seq = 0
        self._send_times: dict = {}
        self._send_order: deque = deque()

        self.locked_addr: tuple | None = None
        self.telemetry: proto.Telemetry | None = None
        self.last_telemetry_at = 0.0
        self.rtt_ms: float | None = None
        self._rtt_window: deque = deque(maxlen=20)
        self._telemetry_times: deque = deque(maxlen=64)

        self.tx_count = 0
        self.rx_count = 0
        self.bad_count = 0
        # Telemetri sehat (magic/versi/CRC benar) tapi dari unit_id lain --
        # mis. mobil unit 2 yang kebetulan terdengar oleh ground station
        # unit 1. Dihitung terpisah dari bad_count karena ini bukan
        # kerusakan paket, murni bukan untuk kita. Lihat docs/protocol.md
        # bagian 7.
        self.foreign_count = 0

        self._stop = threading.Event()
        self._rx_thread = threading.Thread(
            target=self._rx_loop, name="telemetry", daemon=True
        )
        self._rx_thread.start()

    # -- keadaan ---------------------------------------------------------
    @property
    def locked(self) -> bool:
        """True setelah mobil pernah membalas, sehingga alamatnya pasti."""
        return self.locked_addr is not None

    @property
    def connected(self) -> bool:
        """True selama telemetri masih mengalir dalam batas waktu."""
        with self._lock:
            last = self.last_telemetry_at
        if last == 0.0:
            return False
        return (time.monotonic() - last) <= self.timeout

    @property
    def telemetry_hz(self) -> float:
        """Laju telemetri terukur dalam 2 detik terakhir (harusnya ~10 Hz)."""
        now = time.monotonic()
        with self._lock:
            times = [t for t in self._telemetry_times if now - t <= 2.0]
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return 0.0 if span <= 0 else (len(times) - 1) / span

    @property
    def target_description(self) -> str:
        if self.locked_addr:
            return f"{self.locked_addr[0]}:{self.locked_addr[1]}"
        return f"{self.car_addr[0]} + broadcast (mencari)"

    # -- pengiriman ------------------------------------------------------
    def send(
        self, steer: float, throttle: float, armed: bool, brake: float = 0.0,
        *, servo_calibration: bool = False,
    ) -> None:
        """Kirim satu paket kendali.

        steer/throttle dalam rentang -1..1, brake dalam rentang 0..1.
        """
        # Calibration is steering-only by construction. It never carries the
        # armed flag and cannot carry motor/brake output.
        if servo_calibration:
            armed = False
            throttle = 0.0
            brake = 0.0
        # Pengaman berlapis: arming tidak boleh terkirim sebelum tautan terkunci.
        if armed and not self.locked:
            armed = False

        flags = proto.FLAG_SERVO_CALIBRATION if servo_calibration else 0
        if armed:
            flags |= proto.FLAG_ARMED

        with self._lock:
            self._seq = (self._seq + 1) & 0xFFFF
            seq = self._seq
            self._send_times[seq] = time.monotonic()
            self._send_order.append(seq)
            while len(self._send_order) > 256:
                self._send_times.pop(self._send_order.popleft(), None)

        packet = proto.pack_control(
            unit_id=self.unit_id,
            seq=seq,
            flags=flags,
            steer=int(round(steer * proto.AXIS_MAX)),
            throttle=int(round(throttle * proto.AXIS_MAX)),
            brake=int(round(max(0.0, min(1.0, brake)) * 255)),
        )

        targets = (
            [self.locked_addr] if self.locked else [self.car_addr, self.broadcast_addr]
        )
        for addr in targets:
            try:
                self.sock.sendto(packet, addr)
                self.tx_count += 1
            except OSError:
                # Jaringan sedang tidak tersedia (hotspot mati, adapter turun).
                # Bukan kondisi fatal: failsafe di mobil yang akan bertindak.
                pass

    # -- penerimaan ------------------------------------------------------
    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(256)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return

            arrived = time.monotonic()
            telemetry = proto.parse_telemetry(data)
            if telemetry is None:
                with self._lock:
                    self.bad_count += 1
                continue

            if telemetry.unit_id != self.unit_id:
                # Mobil lain menjawab -- BUKAN dianggap rusak, dan yang
                # penting TIDAK mengunci locked_addr ke alamat itu. Inilah
                # yang membuat discovery broadcast aman dipertahankan dengan
                # 3 mobil di satu jaringan: broadcast boleh terdengar oleh
                # semua mobil, tapi hanya balasan dari unit kita sendiri yang
                # pernah dianggap sebagai "mobil ditemukan". Lihat
                # docs/protocol.md bagian 7.
                with self._lock:
                    self.foreign_count += 1
                continue

            with self._lock:
                self.rx_count += 1
                self.telemetry = telemetry
                self.last_telemetry_at = arrived
                self._telemetry_times.append(arrived)

                if self.locked_addr is None:
                    self.locked_addr = addr

                sent_at = self._send_times.get(telemetry.seq_echo)
                if sent_at is not None:
                    self._rtt_window.append((arrived - sent_at) * 1000.0)
                    self.rtt_ms = sum(self._rtt_window) / len(self._rtt_window)

    def poll(self) -> None:
        """Disediakan agar pemanggil boleh memanggilnya tiap loop.

        Penerimaan sudah ditangani thread telemetri, jadi di sini tidak ada
        pekerjaan tersisa. Dibiarkan ada supaya alur loop utama tetap terbaca
        jelas dan urutan kirim/terima tidak menjadi implisit.
        """
        return

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self._rx_thread.join(timeout=1.0)
