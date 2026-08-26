"""Ukur latensi video FPV (glass-to-glass) tanpa perlu kamera HP.

Cara kerjanya: layar kiri menampilkan penghitung milidetik raksasa. Anda
arahkan kamera mobil ke layar itu. Layar kanan menampilkan stream yang
kembali dari kamera -- yang isinya adalah gambar penghitung beberapa saat
LALU, karena tertunda oleh capture, encode, WiFi, dan decode.

Tekan SPASI untuk membekukan keduanya. Selisih antara angka kiri (sekarang)
dan angka kanan (yang terlihat di video) adalah latensi sesungguhnya.

Ini mengukur SELURUH rantai, bukan cuma jaringan: sensor -> JPEG -> WiFi ->
decode -> tampil. Itulah angka yang benar-benar Anda rasakan saat mengemudi.

Jalankan:
    python latency_test.py
    python latency_test.py --cam http://192.168.8.60/stream
    python latency_test.py --cam http://127.0.0.1:8080/stream   # uji dgn fake_cam
"""

from __future__ import annotations

import argparse
import io
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygame

from rcground import config as cfg
from rcground.video import MjpegStream

PANEL_W, PANEL_H = 640, 480
FOOTER_H = 190
WIDTH, HEIGHT = PANEL_W * 2, PANEL_H + FOOTER_H

BG = (10, 11, 14)
PANEL = (20, 22, 28)
WHITE = (245, 247, 250)
DIM = (150, 158, 170)
GREEN = (64, 214, 122)
AMBER = (240, 186, 62)
RED = (236, 84, 84)
BLUE = (86, 168, 246)

# Penghitung ditampilkan sebagai 5 digit milidetik (membungkus tiap 100 detik).
# Lima digit cukup pendek untuk terbaca lewat kamera VGA, dan 100 detik jauh
# lebih lama daripada latensi mana pun yang mungkin terjadi.
WRAP_MS = 100000


def load_font(size: int, bold: bool = False):
    for name in ("consolas", "dejavusansmono", "couriernew"):
        try:
            return pygame.font.SysFont(name, size, bold=bold)
        except Exception:  # noqa: BLE001
            continue
    return pygame.font.Font(None, size)


class LatencyTester:
    def __init__(self, url: str) -> None:
        pygame.init()
        pygame.display.set_caption("Uji Latensi Video — RC Car")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))

        self.font_huge = load_font(190, bold=True)
        self.font = load_font(20)
        self.font_small = load_font(15)
        self.font_mid = load_font(28, bold=True)

        self.url = url
        # decode=True supaya alat ini mengukur jalur yang SAMA PERSIS dengan
        # main.py. Kalau di sini dekode dikerjakan di loop gambar sementara
        # aplikasi asli mengerjakannya di thread video, angka yang keluar
        # bukan latensi yang benar-benar dirasakan saat mengemudi -- ia
        # memuat perlambatan yang hanya ada di alat ukurnya sendiri.
        self.video = MjpegStream(url, timeout=3.0, decode=True).start()

        self.start = time.monotonic()
        self.frozen = False
        self.frozen_ms = 0
        self.frozen_frame: pygame.Surface | None = None
        self.typed = ""
        self.samples: list[float] = []
        self.message = ""

        self._surface: pygame.Surface | None = None
        self._frame_id = -1

    # -- penghitung ------------------------------------------------------
    def now_ms(self) -> int:
        return int((time.monotonic() - self.start) * 1000) % WRAP_MS

    # -- video -----------------------------------------------------------
    def _decode_latest(self) -> None:
        # Sejajar dengan main.py: dekode sudah dikerjakan thread video, di
        # sini tinggal convert(). Jalur cadangan tetap ada untuk frame yang
        # gagal didekode di sana.
        surface, frame_id = self.video.latest_surface()
        if frame_id == self._frame_id:
            return
        if surface is None:
            jpeg, frame_id = self.video.latest()
            if jpeg is None or frame_id == self._frame_id:
                return
            try:
                surface = pygame.image.load(io.BytesIO(jpeg), "f.jpg")
            except pygame.error:
                self._frame_id = frame_id
                return
        self._surface = surface.convert()
        self._frame_id = frame_id

    # -- pembekuan -------------------------------------------------------
    def freeze(self) -> None:
        # Ambil angka penghitung DULU, baru frame -- supaya kalau ada jeda
        # sepersekian milidetik di antaranya, latensi terhitung sedikit
        # lebih kecil, bukan lebih besar. Lebih baik konservatif.
        self.frozen_ms = self.now_ms()
        self.frozen_frame = self._surface.copy() if self._surface else None
        self.frozen = True
        self.typed = ""
        self.message = "Baca angka di panel kanan, ketik di sini, lalu ENTER"

    def submit(self) -> None:
        if not self.typed.isdigit():
            self.message = "Ketik hanya angka yang terbaca di video"
            return

        seen = int(self.typed)
        delta = self.frozen_ms - seen
        # Tangani pembungkusan penghitung di 100000.
        if delta < 0:
            delta += WRAP_MS

        if delta > 5000:
            self.message = f"{delta} ms tidak masuk akal - salah baca angkanya?"
            self.typed = ""
            return

        self.samples.append(float(delta))
        self.message = f"Tercatat {delta} ms  (sampel ke-{len(self.samples)})"
        self.typed = ""
        self.frozen = False

    # -- gambar ----------------------------------------------------------
    def draw(self) -> None:
        self.screen.fill(BG)
        self._draw_counter_panel()
        self._draw_video_panel()
        self._draw_footer()
        pygame.display.flip()

    def _draw_counter_panel(self) -> None:
        rect = pygame.Rect(0, 0, PANEL_W, PANEL_H)
        pygame.draw.rect(self.screen, (0, 0, 0), rect)

        value = self.frozen_ms if self.frozen else self.now_ms()
        text = f"{value:05d}"

        image = self.font_huge.render(text, True, WHITE)
        self.screen.blit(image, image.get_rect(center=rect.center))

        label = "PENGHITUNG (BEKU)" if self.frozen else "PENGHITUNG (HIDUP)"
        color = AMBER if self.frozen else GREEN
        self.screen.blit(
            self.font.render(label, True, color), (14, 12)
        )
        self.screen.blit(
            self.font_small.render(
                "Arahkan kamera mobil ke area hitam ini", True, DIM), (14, 40)
        )

    def _draw_video_panel(self) -> None:
        rect = pygame.Rect(PANEL_W, 0, PANEL_W, PANEL_H)
        pygame.draw.rect(self.screen, PANEL, rect)

        surface = self.frozen_frame if self.frozen else self._surface
        if surface is not None:
            scale = min(PANEL_W / surface.get_width(), PANEL_H / surface.get_height())
            size = (int(surface.get_width() * scale), int(surface.get_height() * scale))
            scaled = pygame.transform.smoothscale(surface, size)
            self.screen.blit(scaled, scaled.get_rect(center=rect.center))
        else:
            msg = "menunggu video..." if not self.video.error else str(self.video.error)[:44]
            image = self.font.render(msg, True, DIM)
            self.screen.blit(image, image.get_rect(center=rect.center))

        label = "VIDEO (BEKU)" if self.frozen else "VIDEO (HIDUP)"
        color = AMBER if self.frozen else GREEN
        self.screen.blit(self.font.render(label, True, color), (PANEL_W + 14, 12))
        self.screen.blit(
            self.font_small.render(f"{self.video.fps:.0f} fps", True, DIM),
            (PANEL_W + 14, 40),
        )

    def _draw_footer(self) -> None:
        top = PANEL_H
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(0, top, WIDTH, FOOTER_H))
        pygame.draw.line(self.screen, (50, 56, 66), (0, top), (WIDTH, top), 1)

        y = top + 14
        if self.frozen:
            self.screen.blit(
                self.font_mid.render(
                    f"Angka di video: {self.typed or '_____'}", True, BLUE), (20, y))
            y += 40
            self.screen.blit(
                self.font.render(
                    f"Penghitung saat dibekukan: {self.frozen_ms:05d}", True, DIM),
                (20, y))
        else:
            self.screen.blit(
                self.font_mid.render("SPASI = bekukan & ukur", True, WHITE), (20, y))
            y += 40
            self.screen.blit(
                self.font.render(
                    "Ambil minimal 5 sampel supaya hasilnya bisa dipercaya",
                    True, DIM), (20, y))

        if self.message:
            self.screen.blit(
                self.font_small.render(self.message, True, AMBER),
                (20, top + FOOTER_H - 52))

        self.screen.blit(
            self.font_small.render(
                "SPASI bekukan  |  ENTER kirim  |  BACKSPACE hapus  |  "
                "R reset sampel  |  ESC keluar", True, DIM),
            (20, top + FOOTER_H - 28))

        self._draw_stats(top)

    def _draw_stats(self, top: int) -> None:
        x = WIDTH - 380
        y = top + 14
        self.screen.blit(self.font.render("HASIL", True, WHITE), (x, y))
        y += 30

        if not self.samples:
            self.screen.blit(
                self.font_small.render("belum ada sampel", True, DIM), (x, y))
            return

        mean = statistics.mean(self.samples)
        median = statistics.median(self.samples)
        color = GREEN if median < 200 else AMBER if median < 350 else RED

        rows = [
            ("jumlah sampel", f"{len(self.samples)}", DIM),
            ("median", f"{median:.0f} ms", color),
            ("rata-rata", f"{mean:.0f} ms", DIM),
            ("min / maks", f"{min(self.samples):.0f} / {max(self.samples):.0f} ms", DIM),
        ]
        for label, value, col in rows:
            self.screen.blit(self.font_small.render(label, True, DIM), (x, y))
            self.screen.blit(self.font_small.render(value, True, col), (x + 150, y))
            y += 22

        if len(self.samples) >= 3:
            spread = max(self.samples) - min(self.samples)
            if spread > 150:
                self.screen.blit(
                    self.font_small.render(
                        "sebaran lebar - stream tidak stabil", True, AMBER),
                    (x, y + 4))

    # -- loop ------------------------------------------------------------
    def run(self) -> int:
        print(f"Menguji latensi terhadap {self.url}")
        print("Arahkan kamera mobil ke panel kiri, lalu tekan SPASI di jendela ini.")
        clock = pygame.time.Clock()
        running = True

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE and not self.frozen:
                        self.freeze()
                    elif event.key == pygame.K_r:
                        self.samples.clear()
                        self.message = "Sampel direset"
                    elif self.frozen:
                        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.submit()
                        elif event.key == pygame.K_BACKSPACE:
                            self.typed = self.typed[:-1]
                        elif event.unicode.isdigit() and len(self.typed) < 5:
                            self.typed += event.unicode

            if not self.frozen:
                self._decode_latest()
            self.draw()
            clock.tick(60)

        self.video.stop()
        pygame.quit()

        if self.samples:
            print(f"\n{len(self.samples)} sampel")
            print(f"  median    : {statistics.median(self.samples):.0f} ms")
            print(f"  rata-rata : {statistics.mean(self.samples):.0f} ms")
            print(f"  min / maks: {min(self.samples):.0f} / {max(self.samples):.0f} ms")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Uji latensi video RC Car")
    parser.add_argument("--cam", metavar="URL", help="timpa URL stream dari config.yaml")
    args = parser.parse_args()

    url = args.cam or cfg.load_config()["camera"]["stream_url"]
    return LatencyTester(url).run()


if __name__ == "__main__":
    raise SystemExit(main())
