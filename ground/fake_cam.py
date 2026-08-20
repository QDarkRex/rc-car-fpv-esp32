"""Simulator ESP32-CAM — mengeluarkan stream MJPEG di format yang sama persis.

Boundary, header bagian, dan urutan potongannya disalin dari streamHandler()
di firmware/rc_cam_esp32/rc_cam_esp32.ino, jadi apa yang Anda uji di sini
benar-benar apa yang nanti dikirim kamera sungguhan.

Gambarnya berupa pola uji bergerak, cukup untuk memastikan video sampai,
HUD tergambar di atasnya, dan latensi terasa wajar.

Jalankan:
    python fake_cam.py
    python fake_cam.py --port 8080 --fps 15 --size 640x480

Lalu arahkan ground station ke sana:
    python main.py --car 127.0.0.1 --cam http://127.0.0.1:8080/stream
"""

from __future__ import annotations

import argparse
import io
import math
import socket
import threading
import time

import pygame

BOUNDARY = b"rccarframeboundary"   # sama dengan PART_BOUNDARY di firmware


def parse_size(text: str) -> tuple:
    width, _, height = text.lower().partition("x")
    return int(width), int(height)


class FakeCamera:
    def __init__(self, host: str, port: int, fps: float, size: tuple) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(4)
        self.fps = fps
        self.size = size
        self.clients = 0

        pygame.init()
        pygame.font.init()
        self.font = pygame.font.Font(None, max(18, size[1] // 12))
        self.surface = pygame.Surface(size)

    def render(self, index: int) -> bytes:
        """Pola uji: latar bergradasi, kotak bergerak, dan nomor frame."""
        width, height = self.size
        phase = index * 0.06

        self.surface.fill((18, 20, 26))

        # Garis horizon dan grid perspektif sederhana, supaya gerakan terlihat.
        horizon = height // 2
        pygame.draw.line(self.surface, (70, 78, 92), (0, horizon), (width, horizon), 2)
        for i in range(-6, 7):
            offset = (i * 60 + int(phase * 40) % 60)
            pygame.draw.line(
                self.surface, (44, 50, 62),
                (width // 2 + offset * 3, height), (width // 2 + offset, horizon), 1
            )
        for i in range(1, 7):
            y = horizon + int((height - horizon) * (i / 6.0) ** 2)
            pygame.draw.line(self.surface, (44, 50, 62), (0, y), (width, y), 1)

        # Objek bergerak, memberi sesuatu untuk diikuti mata.
        x = int(width / 2 + math.sin(phase) * width * 0.32)
        y = int(horizon + 30 + math.cos(phase * 0.7) * 18)
        pygame.draw.circle(self.surface, (86, 168, 246), (x, y), max(8, height // 24))

        label = self.font.render(f"SIMULASI  frame {index}", True, (236, 240, 245))
        self.surface.blit(label, (12, 10))
        clock = self.font.render(time.strftime("%H:%M:%S"), True, (150, 158, 170))
        self.surface.blit(clock, (12, height - clock.get_height() - 10))

        buffer = io.BytesIO()
        pygame.image.save(self.surface, buffer, "frame.jpg")
        return buffer.getvalue()

    def serve_client(self, conn: socket.socket, addr) -> None:
        self.clients += 1
        print(f"[FAKE CAM] klien tersambung dari {addr[0]} ({self.clients} aktif)")
        try:
            conn.recv(2048)
            conn.sendall(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: multipart/x-mixed-replace;boundary=" + BOUNDARY + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"X-Framerate: 30\r\n\r\n"
            )
            index = 0
            period = 1.0 / self.fps
            next_frame = time.monotonic()
            while True:
                jpeg = self.render(index)
                conn.sendall(b"\r\n--" + BOUNDARY + b"\r\n")
                conn.sendall(
                    b"Content-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg)
                )
                conn.sendall(jpeg)
                index += 1
                next_frame += period
                delay = next_frame - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_frame = time.monotonic()
        except OSError:
            pass
        finally:
            self.clients -= 1
            print(f"[FAKE CAM] klien terputus ({self.clients} aktif)")
            try:
                conn.close()
            except OSError:
                pass

    def run(self) -> None:
        while True:
            conn, addr = self.sock.accept()
            # Render JPEG dilakukan per klien; cukup untuk satu-dua penonton.
            threading.Thread(
                target=self.serve_client, args=(conn, addr), daemon=True
            ).start()


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulator ESP32-CAM (stream MJPEG)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--size", default="640x480", help="mis. 640x480 atau 320x240")
    args = ap.parse_args()

    size = parse_size(args.size)
    try:
        camera = FakeCamera(args.host, args.port, args.fps, size)
    except OSError as exc:
        print(f"[FAKE CAM] gagal bind {args.host}:{args.port} -> {exc}")
        return 1

    url = f"http://{args.host}:{args.port}/stream"
    print(f"[FAKE CAM] stream di  {url}")
    print(f"[FAKE CAM] {size[0]}x{size[1]} @ {args.fps:g} fps")
    print(f"[FAKE CAM] uji cepat:  python main.py --car 127.0.0.1 --cam {url}")
    print("[FAKE CAM] Ctrl+C untuk berhenti")

    try:
        camera.run()
    except KeyboardInterrupt:
        print("\n[FAKE CAM] berhenti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
