"""Simulator mobil — meniru firmware ESP32 di sisi protokol.

Gunanya: menguji seluruh aplikasi darat (kalibrasi stir, kurva gas, HUD,
failsafe) tanpa menyentuh hardware sama sekali.

Semantik arming dan failsafe di sini sengaja dibuat identik dengan firmware,
jadi kalau failsafe lolos uji di sini, perilakunya sama di mobil sungguhan.

Jalankan:
    python fake_car.py
    python fake_car.py --unit 2      # simulasikan mobil unit 2
    python fake_car.py --drop 20     # buang 20% paket, uji ketahanan link
"""

from __future__ import annotations

import argparse
import random
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rcground import protocol as proto

FAILSAFE_TIMEOUT = 0.300      # detik — harus sama dengan FAILSAFE_TIMEOUT_MS firmware
TELEMETRY_EVERY_N = 5         # balas tiap 5 paket kontrol -> 10 Hz saat kontrol 50 Hz
BATT_FULL_MV = 16800          # 4S terisi penuh
BATT_LOW_MV = 14000           # ambang peringatan 4S
DRAIN_IDLE = 12.0             # mV per detik saat diam
DRAIN_FULL = 320.0            # mV per detik tambahan pada gas penuh


class FakeCar:
    def __init__(self, port: int, drop_percent: float, unit: int = 1) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # SENGAJA TANPA SO_REUSEADDR. Kalau dua simulator bisa bind ke port
        # yang sama, instance basi diam-diam ikut menjawab paket dan Anda akan
        # menguji kode versi lama tanpa sadar. Lebih baik gagal terang-terangan.
        self.sock.bind(("0.0.0.0", port))
        self.sock.setblocking(False)
        self.drop_percent = drop_percent
        self.unit = unit

        self.boot = time.monotonic()
        self.armed = False
        self.failsafe = True
        self.prev_armed_flag = False
        self.last_valid = 0.0
        self.seq_echo = 0
        self.peer: tuple[str, int] | None = None

        self.steer = 0
        self.throttle = 0
        self.applied_throttle = 0

        self.vbat_mv = float(BATT_FULL_MV)
        self.rx_count = 0
        self.bad_count = 0
        self.dropped = 0
        # Paket sehat tapi ditujukan ke unit lain -- lihat docs/protocol.md
        # bagian 7. Dipisah dari bad_count karena bukan kerusakan protokol.
        self.foreign_count = 0

    # -- penerimaan ------------------------------------------------------
    def poll(self) -> None:
        while True:
            try:
                data, addr = self.sock.recvfrom(256)
            except BlockingIOError:
                return
            except OSError:
                return

            if self.drop_percent and random.random() * 100.0 < self.drop_percent:
                self.dropped += 1
                continue

            ctrl = proto.parse_control(data)
            if ctrl is None:
                # Paket rusak TIDAK menyegarkan pewaktu failsafe.
                self.bad_count += 1
                continue

            if ctrl.unit_id != self.unit:
                # Sama seperti firmware sungguhan: paket sehat tapi bukan
                # untuk unit ini dibuang PERSIS seperti paket rusak -- TIDAK
                # menyegarkan pewaktu failsafe. Lihat docs/protocol.md
                # bagian 7 dan link.cpp::receivePackets().
                self.foreign_count += 1
                continue

            self.rx_count += 1
            self.peer = addr
            self.last_valid = time.monotonic()
            self.seq_echo = ctrl.seq
            self.steer = ctrl.steer
            self.throttle = ctrl.throttle
            # Paket valid berarti tautan hidup. Failsafe murni soal tautan;
            # apakah boleh bergerak diatur terpisah oleh flag armed.
            self.failsafe = False

            # Arming hanya pada transisi 0 -> 1, persis seperti firmware.
            if ctrl.armed and not self.prev_armed_flag:
                self.armed = True
            elif not ctrl.armed:
                self.armed = False
            self.prev_armed_flag = ctrl.armed

            # Balas telemetri langsung pada paket kontrol tertentu, bukan dari
            # timer bebas. Dengan begitu seq_echo terkirim segera dan angka RTT
            # di HUD benar-benar waktu tempuh pulang-pergi.
            if ctrl.seq % TELEMETRY_EVERY_N == 0:
                self.send_telemetry()

    # -- logika kendali --------------------------------------------------
    def update(self, dt: float) -> None:
        if time.monotonic() - self.last_valid > FAILSAFE_TIMEOUT:
            if not self.failsafe:
                print("\n[FAKE CAR] FAILSAFE - paket kontrol putus, motor dinetralkan")
            self.failsafe = True
            self.armed = False
            # KUNCI KE POSISI TINGGI, bukan direset ke False.
            #
            # Kalau di-reset ke False, paket pertama yang datang setelah WiFi
            # pulih -- yang masih membawa flag ARMED=1 dari sebelum putus --
            # akan terlihat seperti transisi 0->1 baru, dan mobil arm sendiri
            # lalu langsung lari. Dengan dikunci tinggi, sisi darat wajib
            # mengirim ARMED=0 dulu sebelum ARMED=1 berpengaruh lagi.
            self.prev_armed_flag = True

        self.applied_throttle = self.throttle if (self.armed and not self.failsafe) else 0

        load = abs(self.applied_throttle) / proto.AXIS_MAX
        self.vbat_mv -= (DRAIN_IDLE + DRAIN_FULL * load) * dt
        self.vbat_mv = max(9000.0, self.vbat_mv)

    # -- telemetri -------------------------------------------------------
    def send_telemetry(self) -> None:
        if self.peer is None:
            return
        flags = 0
        if self.armed:
            flags |= proto.TFLAG_ARMED
        if self.failsafe:
            flags |= proto.TFLAG_FAILSAFE
        if self.vbat_mv < BATT_LOW_MV:
            flags |= proto.TFLAG_LOWBATT

        pkt = proto.pack_telemetry(
            unit_id=self.unit,
            seq_echo=self.seq_echo,
            vbat_mv=int(self.vbat_mv),
            rssi=random.randint(-62, -48),
            flags=flags,
            uptime_ms=int((time.monotonic() - self.boot) * 1000),
        )
        try:
            self.sock.sendto(pkt, self.peer)
        except OSError:
            pass

    def status_line(self) -> str:
        if self.failsafe:
            state = "FAILSAFE"
        elif self.armed:
            state = "ARMED   "
        else:
            state = "DISARMED"
        bar_steer = self._bar(self.steer / proto.AXIS_MAX, signed=True)
        bar_thr = self._bar(self.applied_throttle / proto.AXIS_MAX, signed=True)
        return (
            f"UNIT {self.unit} | {state} | stir {bar_steer} {self.steer:+5d} "
            f"| gas {bar_thr} {self.applied_throttle:+5d} "
            f"| {self.vbat_mv / 1000:5.2f}V | rx {self.rx_count} "
            f"bad {self.bad_count} asing {self.foreign_count} drop {self.dropped}"
        )

    @staticmethod
    def _bar(value: float, signed: bool = False, width: int = 11) -> str:
        cells = ["-"] * width
        mid = width // 2
        if signed:
            pos = int(round(mid + value * mid))
            cells[mid] = "|"
            cells[max(0, min(width - 1, pos))] = "#"
        return "[" + "".join(cells) + "]"


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulator mobil RC untuk uji sisi darat")
    ap.add_argument("--port", type=int, default=proto.CONTROL_PORT)
    ap.add_argument(
        "--unit",
        type=int,
        default=1,
        choices=(1, 2, 3),
        metavar="N",
        help="unit_id yang disimulasikan (1/2/3, default 1) -- lihat docs/protocol.md bagian 7",
    )
    ap.add_argument(
        "--drop",
        type=float,
        default=0.0,
        metavar="PCT",
        help="buang PCT%% paket masuk secara acak, untuk menguji ketahanan link",
    )
    args = ap.parse_args()

    try:
        car = FakeCar(args.port, args.drop, args.unit)
    except OSError as exc:
        print(f"[FAKE CAR] gagal bind UDP :{args.port} -> {exc}")
        print("[FAKE CAR] kemungkinan besar masih ada simulator lain yang jalan.")
        return 1

    print(f"[FAKE CAR] mendengarkan UDP :{args.port}, unit {args.unit}")
    if args.drop:
        print(f"[FAKE CAR] simulasi kehilangan paket {args.drop}%")
    print("[FAKE CAR] Ctrl+C untuk berhenti\n")

    last_print = 0.0
    last_tick = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now

            # update() lebih dulu supaya status failsafe sudah mutakhir saat
            # poll() membalas telemetri di dalam siklus yang sama.
            car.update(dt)
            car.poll()

            if now - last_print >= 0.1:
                last_print = now
                print("\r" + car.status_line(), end="", flush=True)

            time.sleep(0.002)
    except KeyboardInterrupt:
        print("\n[FAKE CAR] berhenti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
