"""Simulator kamera UDP — pasangan fake_cam.py untuk firmware rc_cam_esp32_udp.

Mengirim pola uji bergerak sebagai fragmen UDP, dengan format yang sama
persis dengan firmware. Menunggu paket subscribe lebih dulu, dan berhenti
mengirim kalau subscribe berhenti datang — meniru perilaku firmware.

Yang membuat simulator ini berguna: opsi --drop membuang fragmen secara
acak, sehingga perilaku pada jaringan buruk bisa diuji di meja. Itu
justru kasus yang menjadi alasan jalur UDP ini ada.

Jalankan:
    python fake_cam_udp.py
    python fake_cam_udp.py --unit 3 --drop 5 --fps 20
"""

from __future__ import annotations

import argparse
import io
import math
import random
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygame

from rcground import protocol as proto

SUBSCRIBE_TIMEOUT = 3.0


def render(surface, font, index: int, size: tuple) -> bytes:
    """Pola uji: gradien, kotak bergerak, dan nomor frame."""
    width, height = size
    phase = index * 0.06
    surface.fill((18, 20, 26))

    horizon = height // 2
    pygame.draw.line(surface, (60, 68, 84), (0, horizon), (width, horizon), 2)
    for i in range(-6, 7):
        x = width // 2 + i * (width // 8)
        pygame.draw.line(surface, (40, 46, 58), (x, horizon), (width // 2, height), 1)

    box = int(min(width, height) * 0.18)
    cx = int(width / 2 + math.sin(phase) * width * 0.32)
    cy = int(horizon + math.cos(phase * 0.7) * height * 0.18)
    pygame.draw.rect(surface, (86, 168, 246), (cx - box // 2, cy - box // 2, box, box),
                     border_radius=6)

    label = font.render(f"UDP {index}", True, (236, 240, 245))
    surface.blit(label, (12, 10))

    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, "frame.jpg")
    return buffer.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulator kamera UDP RC Car")
    ap.add_argument("--unit", type=int, default=1, choices=(1, 2, 3))
    ap.add_argument("--port", type=int, default=proto.VIDEO_PORT)
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--size", default="640x480")
    ap.add_argument(
        "--drop", type=float, default=0.0, metavar="PCT",
        help="buang PCT%% fragmen secara acak -- meniru jaringan buruk",
    )
    args = ap.parse_args()

    width, _, height = args.size.lower().partition("x")
    size = (int(width), int(height))

    pygame.init()
    pygame.font.init()
    font = pygame.font.Font(None, max(18, size[1] // 12))
    surface = pygame.Surface(size)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", args.port))
    except OSError as exc:
        print(f"[FAKE CAM UDP] gagal bind :{args.port} -> {exc}")
        return 1
    sock.settimeout(0.01)

    print(f"[FAKE CAM UDP] unit {args.unit}, menunggu subscribe di :{args.port}")
    print(f"[FAKE CAM UDP] {size[0]}x{size[1]} @ {args.fps:g} fps, drop {args.drop:g}%")
    print("[FAKE CAM UDP] Ctrl+C untuk berhenti")

    subscriber = None
    last_subscribe = 0.0
    frame_id = 0
    frames_sent = 0
    frags_dropped = 0
    next_frame = time.monotonic()
    last_report = time.monotonic()

    try:
        while True:
            # -- terima subscribe
            try:
                data, addr = sock.recvfrom(64)
                if proto.parse_subscribe(data) == args.unit:
                    if addr != subscriber:
                        print(f"[FAKE CAM UDP] pelanggan baru: {addr[0]}:{addr[1]}")
                    subscriber = addr
                    last_subscribe = time.monotonic()
            except (TimeoutError, socket.timeout):
                pass
            except OSError:
                break

            now = time.monotonic()
            active = subscriber is not None and (now - last_subscribe) <= SUBSCRIBE_TIMEOUT

            if not active:
                if subscriber is not None and (now - last_subscribe) > SUBSCRIBE_TIMEOUT:
                    print("[FAKE CAM UDP] pelanggan hilang - berhenti mengirim")
                    subscriber = None
                time.sleep(0.02)
                continue

            if now < next_frame:
                time.sleep(min(0.005, next_frame - now))
                continue
            next_frame = now + 1.0 / max(1.0, args.fps)

            jpeg = render(surface, font, frame_id, size)
            chunks = [
                jpeg[i:i + proto.VIDEO_PAYLOAD_MAX]
                for i in range(0, len(jpeg), proto.VIDEO_PAYLOAD_MAX)
            ]
            for index, chunk in enumerate(chunks):
                if args.drop > 0 and random.random() * 100.0 < args.drop:
                    frags_dropped += 1
                    continue
                packet = proto.pack_video(
                    args.unit, frame_id, index, len(chunks), chunk
                )
                try:
                    sock.sendto(packet, subscriber)
                except OSError:
                    pass
            frame_id = (frame_id + 1) & 0xFFFF
            frames_sent += 1

            if now - last_report >= 5.0:
                print(f"[FAKE CAM UDP] {frames_sent / 5.0:.1f} fps terkirim | "
                      f"{len(chunks)} fragmen/frame | {frags_dropped} fragmen dibuang")
                frames_sent = 0
                frags_dropped = 0
                last_report = now
    except KeyboardInterrupt:
        print("\n[FAKE CAM UDP] berhenti")
    finally:
        sock.close()
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
