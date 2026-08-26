"""Overlay HUD yang digambar di atas video FPV.

Prinsip tampilan: status kendali harus terbaca dalam sekali lirik sambil
mengemudi. Karena itu status arming memakai banner besar berwarna, dan angka
yang jarang dilihat (uptime, RSSI) ditaruh kecil di pinggir.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

# -- palet -------------------------------------------------------------------
WHITE = (236, 240, 245)
DIM = (150, 158, 170)
PANEL = (14, 16, 20)
GREEN = (64, 214, 122)
AMBER = (240, 186, 62)
RED = (236, 84, 84)
BLUE = (86, 168, 246)
GRID = (90, 98, 112)

# Ambang tegangan untuk paket 4S LiPo.
BATT_FULL_V = 16.8
BATT_WARN_V = 14.8   # ~3,70 V/sel -- mulai bersiap mendarat
BATT_CRIT_V = 14.0   # ~3,50 V/sel -- di bawah ini sel mulai rusak


@dataclass
class HudContext:
    steer: float = 0.0
    throttle: float = 0.0
    gas: float = 0.0
    brake: float = 0.0
    brake_out: float = 0.0
    gear: int = 0
    gear_label: str = "N"
    trim: float = 0.0
    armed: bool = False
    failsafe: bool = False
    link_connected: bool = False
    link_locked: bool = False
    wheel_connected: bool = False
    wheel_name: str = ""
    input_source: str = "none"
    # rtt_ms = bolak-balik ke MOBIL (UDP 4210, lewat gema seq_echo).
    # cam_rtt_ms = bolak-balik ke KAMERA (TCP ke port HTTP-nya).
    # Keduanya modul terpisah di jaringan yang sama, jadi angkanya bisa
    # berbeda -- terutama saat kamera sibuk mengirim frame.
    rtt_ms: float | None = None
    cam_rtt_ms: float | None = None
    video_fps: float = 0.0
    # Jeda terpanjang antar frame -- angka yang mewakili rasa "patah-patah".
    # Dipisah dari video_fps karena fps yang rata-rata tidak bisa
    # menunjukkannya. Lihat MjpegStream.worst_gap_ms.
    video_gap_ms: float = 0.0
    telemetry_hz: float = 0.0
    rssi: int | None = None
    vbat: float | None = None
    low_batt: bool = False
    uptime_ms: int = 0
    target: str = ""
    video_ok: bool = False
    video_error: str | None = None
    max_forward: float = 0.0
    message: str = ""
    sfx_gas: str = ""
    sfx_horn: str = ""
    sfx_arm: str = ""
    # Kalibrasi stir belum ada. Ditampilkan TERUS (bukan lewat `message` yang
    # hilang setelah beberapa detik) karena selama ini benar, stir dan pedal
    # tidak terbaca sama sekali -- itu kondisi yang harus selalu terlihat,
    # bukan pemberitahuan sekali lewat yang mudah terlewat.
    calibration_missing: bool = False


class Hud:
    def __init__(self) -> None:
        pygame.font.init()
        self.font_big = self._load(30, bold=True)
        self.font = self._load(17)
        self.font_small = self._load(14)
        self._blink = 0.0

    @staticmethod
    def _load(size: int, bold: bool = False):
        # Font monospace agar angka tidak bergoyang saat berubah.
        for name in ("consolas", "dejavusansmono", "couriernew"):
            try:
                return pygame.font.SysFont(name, size, bold=bold)
            except Exception:  # noqa: BLE001
                continue
        return pygame.font.Font(None, size)

    # -- primitif --------------------------------------------------------
    def _panel(self, surface, rect, alpha: int = 165) -> None:
        layer = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        layer.fill((*PANEL, alpha))
        surface.blit(layer, rect.topleft)

    def _text(self, surface, text, pos, font=None, color=WHITE, right=False):
        font = font or self.font
        image = font.render(text, True, color)
        rect = image.get_rect()
        if right:
            rect.topright = pos
        else:
            rect.topleft = pos
        surface.blit(image, rect)
        return rect

    def _bipolar_bar(self, surface, rect, value, color, label) -> None:
        """Bar dua arah dengan penanda titik tengah, untuk stir dan gas."""
        pygame.draw.rect(surface, (*PANEL, 200), rect, border_radius=3)
        pygame.draw.rect(surface, GRID, rect, width=1, border_radius=3)

        mid_x = rect.centerx
        value = max(-1.0, min(1.0, value))
        width = int(abs(value) * (rect.width / 2 - 2))
        if width > 0:
            fill = pygame.Rect(0, rect.top + 2, width, rect.height - 4)
            fill.left = mid_x if value > 0 else mid_x - width
            pygame.draw.rect(surface, color, fill, border_radius=2)

        pygame.draw.line(
            surface, WHITE, (mid_x, rect.top + 1), (mid_x, rect.bottom - 1), 1
        )
        self._text(
            surface,
            f"{label} {value:+.2f}",
            (rect.left, rect.top - 18),
            self.font_small,
            DIM,
        )

    # -- gambar utama ----------------------------------------------------
    def draw(self, surface: pygame.Surface, ctx: HudContext, dt: float) -> None:
        self._blink = (self._blink + dt) % 1.0
        width, height = surface.get_size()

        self._draw_status_banner(surface, ctx, width)
        if ctx.calibration_missing:
            self._draw_calibration_warning(surface, width)
        self._draw_bars(surface, ctx, width, height)
        self._draw_telemetry(surface, ctx, width)
        self._draw_footer(surface, ctx, width, height)

    def _draw_calibration_warning(self, surface, width: int) -> None:
        """Pita peringatan tepat di bawah banner status.

        Sengaja tidak berkedip: ini kondisi menetap, bukan kejadian mendadak.
        Yang berkedip adalah FAILSAFE, dan dua hal berkedip sekaligus justru
        membuat keduanya lebih mudah diabaikan.
        """
        rect = pygame.Rect(0, 46, width, 26)
        self._panel(surface, rect, alpha=205)
        text = self._pick_fitting(
            [
                "KALIBRASI BELUM ADA - jalankan Kalibrasi.exe. Stir dan pedal tidak terbaca.",
                "KALIBRASI BELUM ADA - jalankan Kalibrasi.exe dulu",
                "KALIBRASI BELUM ADA",
            ],
            self.font_small,
            width - 24,
        )
        if text:
            image = self.font_small.render(text, True, AMBER)
            surface.blit(image, image.get_rect(center=(width // 2, rect.centery)))

    @staticmethod
    def _pick_fitting(variants, font, max_width: int):
        """Pilih varian teks terpanjang yang masih muat. None kalau tak ada.

        Dipakai agar HUD tetap terbaca saat jendela diperkecil: lebih baik
        menyingkat teks daripada membiarkannya saling menimpa.
        """
        for text in variants:
            if font.size(text)[0] <= max_width:
                return text
        return None

    def _draw_status_banner(self, surface, ctx: HudContext, width: int) -> None:
        if ctx.failsafe or not ctx.link_connected:
            variants = (
                ["FAILSAFE - TAUTAN PUTUS", "TAUTAN PUTUS", "FAILSAFE"]
                if not ctx.link_connected
                else ["FAILSAFE"]
            )
            color = RED
            visible = self._blink < 0.65   # berkedip agar sulit diabaikan
        elif ctx.armed:
            variants, color, visible = ["ARMED"], GREEN, True
        else:
            variants, color, visible = ["DISARMED"], AMBER, True

        rect = pygame.Rect(0, 0, width, 46)
        self._panel(surface, rect, alpha=150)

        limit_text = f"batas maju {int(ctx.max_forward * 100)}%"
        side = max(
            self.font_small.size(ctx.target)[0], self.font_small.size(limit_text)[0]
        )
        gap = width - 2 * side - 32

        label = self._pick_fitting(variants, self.font_big, gap)
        show_sides = label is not None
        if label is None:
            # Tidak ada varian yang muat di antara teks pinggir: teks pinggir
            # yang dikorbankan, karena status arming jauh lebih penting.
            label = self._pick_fitting(variants, self.font_big, width - 24) or variants[-1]

        if visible:
            image = self.font_big.render(label, True, color)
            surface.blit(image, image.get_rect(center=(width // 2, 23)))

        if show_sides:
            self._text(surface, ctx.target, (12, 15), self.font_small, DIM)
            self._text(
                surface, limit_text, (width - 12, 15), self.font_small, DIM, right=True
            )

    def _draw_bars(self, surface, ctx: HudContext, width: int, height: int) -> None:
        bar_w = min(360, width - 40)
        left = (width - bar_w) // 2
        base = height - 96

        self._bipolar_bar(
            surface, pygame.Rect(left, base, bar_w, 20), ctx.steer, BLUE, "STIR"
        )
        self._bipolar_bar(
            surface,
            pygame.Rect(left, base + 44, bar_w, 20),
            ctx.throttle,
            GREEN if ctx.throttle >= 0 else AMBER,
            "GAS",
        )

        if abs(ctx.trim) > 0.001:
            self._text(
                surface,
                f"trim {ctx.trim:+.3f}",
                (left + bar_w, base - 18),
                self.font_small,
                AMBER,
                right=True,
            )

    def _draw_telemetry(self, surface, ctx: HudContext, width: int) -> None:
        # Di jendela yang sangat sempit panel ini akan menutupi seluruh video.
        # Lebih baik disembunyikan daripada membuat video tidak terlihat.
        if width < 300:
            return

        # Tinggi panel diperbesar dari 132 supaya muat 3 baris tambahan info
        # pack SFX aktif (gas/klakson/arm) di bawah baris telemetri lama,
        # lalu +21 lagi untuk baris KENDALI setelah PING dipakai kamera,
        # dan +21 sekali lagi untuk baris PATAH.
        rect = pygame.Rect(width - 172, 56, 160, 246)
        self._panel(surface, rect)

        x_label = rect.left + 10
        x_value = rect.right - 10
        y = rect.top + 8

        def row(label: str, value: str, color=WHITE) -> None:
            nonlocal y
            self._text(surface, label, (x_label, y), self.font_small, DIM)
            self._text(surface, value, (x_value, y - 1), self.font_small, color, right=True)
            y += 21

        # PING = kamera. Ambangnya lebih longgar daripada jalur kendali:
        # ini TCP ke server HTTP yang sedang sibuk mengirim frame, jadi
        # puluhan milidetik masih wajar dan bukan tanda masalah.
        if ctx.cam_rtt_ms is None:
            row("PING", "--", DIM)
        else:
            color = (
                GREEN if ctx.cam_rtt_ms < 60
                else AMBER if ctx.cam_rtt_ms < 150
                else RED
            )
            row("PING", f"{ctx.cam_rtt_ms:.0f} ms", color)

        # Jalur kendali tetap ditampilkan -- inilah angka yang menentukan
        # apakah mobil masih menurut, dan ambangnya jauh lebih ketat.
        if ctx.rtt_ms is None:
            row("KENDALI", "--", DIM)
        else:
            color = GREEN if ctx.rtt_ms < 30 else AMBER if ctx.rtt_ms < 80 else RED
            row("KENDALI", f"{ctx.rtt_ms:.0f} ms", color)

        fps_color = GREEN if ctx.video_fps >= 15 else AMBER if ctx.video_fps > 0 else RED
        row("VIDEO", f"{ctx.video_fps:.0f} fps", fps_color)

        # PATAH: jeda frame terpanjang. Ambangnya dipilih dari yang terlihat
        # mata, bukan angka bulat -- di bawah ~120 ms gerakan masih terbaca
        # menerus; di atas ~250 ms terasa jelas sebagai tersendat.
        if ctx.video_gap_ms <= 0.0:
            row("PATAH", "--", DIM)
        else:
            color = (
                GREEN if ctx.video_gap_ms < 120
                else AMBER if ctx.video_gap_ms < 250
                else RED
            )
            row("PATAH", f"{ctx.video_gap_ms:.0f} ms", color)

        tel_color = GREEN if ctx.telemetry_hz >= 7 else AMBER if ctx.telemetry_hz > 0 else RED
        row("TELEM", f"{ctx.telemetry_hz:.0f} Hz", tel_color)

        if ctx.rssi is None:
            row("SINYAL", "--", DIM)
        else:
            color = GREEN if ctx.rssi > -65 else AMBER if ctx.rssi > -78 else RED
            row("SINYAL", f"{ctx.rssi} dBm", color)

        if ctx.vbat is None:
            row("BATERAI", "--", DIM)
        else:
            if ctx.vbat < BATT_CRIT_V or ctx.low_batt:
                color = RED
            elif ctx.vbat < BATT_WARN_V:
                color = AMBER
            else:
                color = GREEN
            row("BATERAI", f"{ctx.vbat:.2f} V", color)

        row("AKTIF", f"{ctx.uptime_ms // 1000:d} s", DIM)

        # Info pack SFX aktif -- baris lebih pendek daripada row() biasa
        # (label+nilai sejajar kolom) karena judul pack bisa panjang dan
        # perlu ruang penuh selebar panel, bukan cuma separuh kanan seperti
        # nilai telemetri di atas. _pick_fitting menyingkat ke varian yang
        # lebih pendek kalau judul aslinya tidak muat di lebar panel.
        y += 6
        avail = rect.width - 20
        for label, value, color in (
            ("GAS", ctx.sfx_gas, GREEN),
            ("KLAKSON", ctx.sfx_horn, BLUE),
            ("ARM", ctx.sfx_arm, AMBER),
        ):
            full = f"{label} {value}"
            short = f"{label} {value[:18]}" if len(value) > 18 else full
            text = self._pick_fitting([full, short, label], self.font_small, avail) or label
            self._text(surface, text, (x_label, y), self.font_small, color)
            y += 18

        if ctx.vbat is not None and ctx.vbat < BATT_CRIT_V:
            warn = pygame.Rect(rect.left, rect.bottom + 6, rect.width, 24)
            self._panel(surface, warn, alpha=200)
            image = self.font_small.render("BATERAI KRITIS", True, RED)
            surface.blit(image, image.get_rect(center=warn.center))

    def _draw_footer(self, surface, ctx: HudContext, width: int, height: int) -> None:
        rect = pygame.Rect(0, height - 26, width, 26)
        self._panel(surface, rect, alpha=170)

        source = ctx.wheel_name if ctx.wheel_connected else "stir tidak terdeteksi"
        source_color = DIM if ctx.wheel_connected else AMBER
        source_width = self.font_small.size(source)[0]

        # Sisi kanan didahulukan: status stir lebih penting daripada daftar
        # tombol yang toh sudah dihafal setelah beberapa kali pakai.
        if source_width + 32 <= width:
            self._text(
                surface, source, (width - 12, height - 22),
                self.font_small, source_color, right=True,
            )
            available = width - source_width - 36
        else:
            available = width - 24

        if ctx.message:
            left = self._pick_fitting(
                [ctx.message, ctx.message[:40] + "..."], self.font_small, available
            )
            color = AMBER
        else:
            left = self._pick_fitting(
                [
                    "SPASI arm/disarm  |  E stop darurat  |  [ ] trim  |  H klakson  "
                    "|  G/N/M pack suara  |  F5 simpan  |  ESC keluar",
                    "SPASI arm  |  E stop  |  [ ] trim  |  H klakson  |  G/N/M pack  "
                    "|  F5 simpan  |  ESC keluar",
                    "SPASI arm  |  E stop  |  [ ] trim  |  H klakson  |  ESC keluar",
                    "SPASI arm  |  E stop  |  [ ] trim  |  ESC keluar",
                    "SPASI arm  |  E stop  |  ESC keluar",
                    "SPASI arm  |  E stop",
                ],
                self.font_small,
                available,
            )
            color = DIM

        if left:
            self._text(surface, left, (12, height - 22), self.font_small, color)

    # -- layar pengganti saat video mati ---------------------------------
    def draw_no_video(self, surface: pygame.Surface, ctx: HudContext) -> None:
        width, height = surface.get_size()
        surface.fill((10, 11, 14))

        lines = [("MENUNGGU VIDEO", WHITE, self.font_big)]
        if ctx.video_error:
            lines.append((ctx.video_error[:70], DIM, self.font_small))
        lines.append(("kendali tetap berjalan tanpa video", DIM, self.font_small))

        y = height // 2 - 40
        for text, color, font in lines:
            image = font.render(text, True, color)
            surface.blit(image, image.get_rect(center=(width // 2, y)))
            y += font.get_height() + 8
