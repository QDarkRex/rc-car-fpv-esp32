"""Wizard kalibrasi stir PXN V9.

Kenapa perlu: PXN V9 punya saklar mode (DirectInput/XInput, pedal terpisah vs
digabung). Nomor axis berubah mengikuti mode, jadi memakai angka hafalan dari
tutorial mana pun tidak bisa diandalkan.

Wizard ini tidak menebak nomor apa pun. Ia merekam posisi diam semua axis,
lalu saat Anda menggerakkan satu kontrol, axis yang berubah paling besar
itulah yang dipakai. Hasilnya ditulis ke calibration.yaml.

Jalankan:
    python calibrate.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygame

from rcground import config as cfg

WIDTH, HEIGHT = 900, 660
BG = (16, 18, 22)
PANEL = (26, 29, 36)
WHITE = (236, 240, 245)
DIM = (150, 158, 170)
GREEN = (64, 214, 122)
AMBER = (240, 186, 62)
BLUE = (86, 168, 246)
RED = (236, 84, 84)

MOVE_THRESHOLD = 0.35   # perubahan minimum agar sebuah axis dianggap digerakkan


@dataclass
class Step:
    key: str
    title: str
    hint: str


STEPS = [
    Step("rest", "Lepaskan semua pedal, biarkan stir di tengah",
         "Jangan sentuh apa pun, lalu tekan SPASI."),
    Step("left", "Putar stir mentok KIRI dan TAHAN",
         "Tahan di posisi mentok, lalu tekan SPASI."),
    Step("right", "Putar stir mentok KANAN dan TAHAN",
         "Tahan di posisi mentok, lalu tekan SPASI."),
    Step("gas", "Injak pedal GAS penuh dan TAHAN",
         "Tahan sampai mentok, lalu tekan SPASI."),
    Step("brake", "Injak pedal REM penuh dan TAHAN",
         "Tahan sampai mentok, lalu tekan SPASI."),
    Step("arm", "Tekan tombol yang ingin dipakai untuk ARM",
         "Tombol ini yang akan menghidupkan/mematikan motor."),
    Step("estop", "Tekan tombol yang ingin dipakai untuk STOP DARURAT",
         "Pilih tombol yang mudah diraih tanpa melihat."),
    Step("horn", "Tekan tombol yang ingin dipakai untuk KLAKSON",
         "Tombol ini akan membunyikan klakson selama ditahan."),
]


@dataclass
class Result:
    rest: list = field(default_factory=list)
    steer_axis: int | None = None
    steer_min: float = -1.0
    steer_max: float = 1.0
    gas_axis: int | None = None
    gas_pressed: float = 1.0
    brake_axis: int | None = None
    brake_pressed: float = 1.0
    arm_button: int | None = None
    estop_button: int | None = None
    horn_button: int | None = None


@dataclass
class ShifterResult:
    """Hasil kalibrasi tuas gigi. `kind` None berarti dilewati -- calibrate.py
    tidak menulis kunci `shifter` sama sekali ke calibration.yaml, sehingga
    fallback perilaku lama di rcground/wheel.py tetap aktif."""
    kind: str | None = None            # "h_pattern" | "sequential" | None
    gear_buttons: dict = field(default_factory=dict)   # {1: idx, 2: idx, ...}
    reverse_button: int | None = None
    up_button: int | None = None
    down_button: int | None = None


def choose_joystick(screen, font, font_small) -> "pygame.joystick.Joystick | None":
    """Pilih perangkat kalau ada lebih dari satu (mis. dua unit PXN V9)."""
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    if count == 0:
        return None

    sticks = [pygame.joystick.Joystick(i) for i in range(count)]
    for stick in sticks:
        stick.init()
    if count == 1:
        return sticks[0]

    selected = 0
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key in (pygame.K_DOWN, pygame.K_TAB):
                    selected = (selected + 1) % count
                if event.key == pygame.K_UP:
                    selected = (selected - 1) % count
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return sticks[selected]
                if pygame.K_1 <= event.key <= pygame.K_9:
                    index = event.key - pygame.K_1
                    if index < count:
                        return sticks[index]

        screen.fill(BG)
        title = font.render("Pilih perangkat yang dipakai", True, WHITE)
        screen.blit(title, (40, 40))
        hint = font_small.render(
            "Panah atas/bawah lalu ENTER, atau tekan angka. ESC untuk batal.",
            True, DIM,
        )
        screen.blit(hint, (40, 78))

        y = 130
        for i, stick in enumerate(sticks):
            active = i == selected
            rect = pygame.Rect(40, y, WIDTH - 80, 54)
            pygame.draw.rect(screen, PANEL if not active else (38, 52, 72), rect,
                             border_radius=6)
            if active:
                pygame.draw.rect(screen, BLUE, rect, width=2, border_radius=6)
            label = font.render(f"{i + 1}.  {stick.get_name()}", True,
                                WHITE if active else DIM)
            screen.blit(label, (rect.left + 16, rect.top + 8))
            detail = font_small.render(
                f"{stick.get_numaxes()} axis, {stick.get_numbuttons()} tombol",
                True, DIM,
            )
            screen.blit(detail, (rect.left + 16, rect.top + 32))
            y += 66

        # Bantuan membedakan dua unit yang namanya identik.
        note = font_small.render(
            "Tip: kalau kedua nama sama, goyangkan salah satu stir -- "
            "perangkat yang aktif akan terlihat di layar berikutnya.",
            True, AMBER,
        )
        screen.blit(note, (40, y + 16))

        pygame.display.flip()
        clock.tick(60)


def detect_moved_axis(stick, rest: list, exclude: set) -> int | None:
    """Axis mana yang paling jauh berubah dari posisi diamnya."""
    best_axis, best_delta = None, 0.0
    for i in range(stick.get_numaxes()):
        if i in exclude:
            continue
        delta = abs(stick.get_axis(i) - rest[i])
        if delta > best_delta:
            best_axis, best_delta = i, delta
    if best_axis is None or best_delta < MOVE_THRESHOLD:
        return None
    return best_axis


def draw_axes(screen, font_small, stick, rest, result, y0: int) -> None:
    """Tampilkan semua axis secara live, dengan label peran yang sudah dikenali."""
    roles = {}
    if result.steer_axis is not None:
        roles[result.steer_axis] = ("STIR", BLUE)
    if result.gas_axis is not None:
        roles[result.gas_axis] = ("GAS", GREEN)
    if result.brake_axis is not None:
        roles[result.brake_axis] = ("REM", AMBER)

    y = y0
    for i in range(stick.get_numaxes()):
        value = stick.get_axis(i)
        moved = rest and abs(value - rest[i]) > MOVE_THRESHOLD

        role, color = roles.get(i, (None, None))
        label_color = color if role else (WHITE if moved else DIM)
        screen.blit(font_small.render(f"axis {i}", True, label_color), (48, y))

        bar = pygame.Rect(120, y + 2, 420, 14)
        pygame.draw.rect(screen, PANEL, bar, border_radius=3)
        mid = bar.centerx
        width = int(abs(value) * (bar.width / 2 - 2))
        if width:
            fill = pygame.Rect(0, bar.top + 2, width, bar.height - 4)
            fill.left = mid if value > 0 else mid - width
            pygame.draw.rect(screen, color or (BLUE if moved else (70, 76, 88)),
                             fill, border_radius=2)
        pygame.draw.line(screen, DIM, (mid, bar.top), (mid, bar.bottom), 1)

        screen.blit(font_small.render(f"{value:+.3f}", True, label_color), (556, y))
        if role:
            screen.blit(font_small.render(role, True, color), (630, y))
        y += 22


def draw_buttons(screen, font_small, stick, result, y0: int) -> None:
    screen.blit(font_small.render("tombol", True, DIM), (48, y0))
    x = 120
    y = y0
    for i in range(stick.get_numbuttons()):
        pressed = stick.get_button(i)
        color = GREEN if pressed else PANEL
        if i == result.arm_button:
            color = BLUE
        elif i == result.estop_button:
            color = RED
        elif i == result.horn_button:
            color = AMBER
        rect = pygame.Rect(x, y, 26, 18)
        pygame.draw.rect(screen, color, rect, border_radius=3)
        highlighted = (result.arm_button, result.estop_button, result.horn_button)
        text_color = BG if (pressed or i in highlighted) else DIM
        label = font_small.render(str(i), True, text_color)
        screen.blit(label, label.get_rect(center=rect.center))
        x += 30
        if x > WIDTH - 90:
            x = 120
            y += 24


def held_button(stick, exclude: set) -> int | None:
    """Tombol mana yang sedang ditekan sekarang, di luar yang sudah dipakai.

    Dipakai untuk tuas H-pattern: posisi gigi diwakili tombol yang aktif
    SELAMA tuas ada di situ (bukan event tekan-lepas), jadi cara paling
    sesuai untuk merekamnya adalah melihat siapa yang aktif saat SPASI
    ditekan -- sama seperti axis stir/pedal direkam pada posisinya saat itu.
    """
    for i in range(stick.get_numbuttons()):
        if i in exclude:
            continue
        if stick.get_button(i):
            return i
    return None


def run_shifter_wizard(screen, font_big, font, font_small, stick) -> ShifterResult:
    """Wizard kalibrasi tuas gigi, dijalankan setelah langkah stop darurat.

    Tekan H untuk H-pattern, S untuk sequential, N untuk melewati (tanpa
    tuas gigi). ESC di titik mana pun membatalkan wizard ini saja -- hasil
    kalibrasi stir/pedal/arm/estop yang sudah direkam sebelumnya tidak hilang.
    """
    result = ShifterResult()
    clock = pygame.time.Clock()

    # -- fase 0: pilih jenis tuas -----------------------------------------
    choosing = True
    while choosing:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return result
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_h:
                    result.kind = "h_pattern"
                    choosing = False
                elif event.key == pygame.K_s:
                    result.kind = "sequential"
                    choosing = False
                elif event.key in (pygame.K_n, pygame.K_ESCAPE):
                    return result   # dilewati, kunci shifter tidak ditulis

        screen.fill(BG)
        screen.blit(font_big.render("Kalibrasi tuas gigi (opsional)", True, WHITE),
                     (40, 40))
        lines = [
            "Jenis tuas apa yang Anda pakai?",
            "",
            "H  = H-pattern (tiap gigi tombol/posisi tersendiri)",
            "S  = Sequential (dua tombol naik/turun)",
            "N  = Tidak pakai tuas gigi -- lewati langkah ini",
        ]
        y = 110
        for line in lines:
            screen.blit(font.render(line, True, DIM if line else WHITE), (40, y))
            y += 30
        pygame.display.flip()
        clock.tick(60)

    # -- fase H-pattern -----------------------------------------------------
    if result.kind == "h_pattern":
        phase = "forward"
        gear = 1
        error = ""
        while phase != "done":
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return result
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        result.kind = None
                        return result
                    if phase == "forward":
                        if event.key == pygame.K_SPACE:
                            used = set(result.gear_buttons.values())
                            btn = held_button(stick, used)
                            if btn is None:
                                error = "Tidak ada tombol yang aktif. Masukkan gigi dan tahan, lalu SPASI."
                            else:
                                result.gear_buttons[gear] = btn
                                gear += 1
                                error = ""
                        elif event.key == pygame.K_RETURN:
                            if result.gear_buttons:
                                phase = "reverse"
                                error = ""
                            else:
                                error = "Rekam minimal satu gigi maju dulu sebelum ENTER."
                    elif phase == "reverse":
                        if event.key == pygame.K_SPACE:
                            used = set(result.gear_buttons.values())
                            btn = held_button(stick, used)
                            if btn is None:
                                error = "Tidak ada tombol yang aktif. Masukkan ke R dan tahan, lalu SPASI."
                            else:
                                result.reverse_button = btn
                                phase = "done"

            screen.fill(BG)
            header = pygame.Rect(0, 0, WIDTH, 96)
            pygame.draw.rect(screen, PANEL, header)
            if phase == "forward":
                title = f"Masukkan ke gigi {gear}, lalu SPASI"
                hint = "Tahan tuas di posisi itu. ENTER kalau gigi maju sudah selesai semua."
            else:
                title = "Masukkan ke posisi R, lalu SPASI"
                hint = "Tahan tuas di posisi R."
            screen.blit(font_big.render(title, True, WHITE), (40, 40))
            screen.blit(font_small.render(hint, True, AMBER), (40, 72))

            y = 120
            if result.gear_buttons:
                recorded = "  ".join(
                    f"gigi {g}=tombol {b}" for g, b in sorted(result.gear_buttons.items())
                )
                screen.blit(font_small.render(recorded, True, GREEN), (40, y))
                y += 26

            draw_buttons(screen, font_small, stick, Result(), y + 10)

            if error:
                screen.blit(font_small.render(error, True, RED), (40, HEIGHT - 56))
            screen.blit(font_small.render("ESC = lewati kalibrasi gigi", True, DIM),
                         (40, HEIGHT - 32))

            pygame.display.flip()
            clock.tick(60)

    # -- fase sequential ------------------------------------------------
    elif result.kind == "sequential":
        phase = "up"
        error = ""
        while phase != "done":
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return result
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        result.kind = None
                        return result
                    if event.key == pygame.K_SPACE:
                        exclude = {result.up_button} if result.up_button is not None else set()
                        btn = held_button(stick, exclude)
                        if btn is None:
                            error = "Tidak ada tombol yang aktif. Tekan/tahan arah yang diminta, lalu SPASI."
                        elif phase == "up":
                            result.up_button = btn
                            phase = "down"
                            error = ""
                        else:
                            result.down_button = btn
                            phase = "done"

            screen.fill(BG)
            header = pygame.Rect(0, 0, WIDTH, 96)
            pygame.draw.rect(screen, PANEL, header)
            if phase == "up":
                title = "Dorong tuas ke arah NAIK, lalu SPASI"
            else:
                title = "Tarik tuas ke arah TURUN, lalu SPASI"
            screen.blit(font_big.render(title, True, WHITE), (40, 40))
            screen.blit(
                font_small.render("Tombol naik/turun boleh momentary (lepas lagi setelahnya).",
                                    True, AMBER), (40, 72))

            draw_buttons(screen, font_small, stick, Result(), 130)

            if error:
                screen.blit(font_small.render(error, True, RED), (40, HEIGHT - 56))
            screen.blit(font_small.render("ESC = lewati kalibrasi gigi", True, DIM),
                         (40, HEIGHT - 32))

            pygame.display.flip()
            clock.tick(60)

    return result


def main() -> int:
    pygame.init()
    pygame.display.set_caption("Kalibrasi Stir — RC Car")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    def load_font(size, bold=False):
        for name in ("consolas", "dejavusansmono", "couriernew"):
            try:
                return pygame.font.SysFont(name, size, bold=bold)
            except Exception:  # noqa: BLE001
                continue
        return pygame.font.Font(None, size)

    font_big = load_font(26, bold=True)
    font = load_font(19)
    font_small = load_font(15)

    stick = choose_joystick(screen, font, font_small)
    if stick is None:
        pygame.quit()
        print("Tidak ada stir terdeteksi (atau dibatalkan).")
        print("Colok PXN V9 lewat USB, pastikan lampunya menyala, lalu ulangi.")
        return 1

    print(f"Perangkat: {stick.get_name()}")
    print(f"  {stick.get_numaxes()} axis, {stick.get_numbuttons()} tombol")

    result = Result(rest=[0.0] * stick.get_numaxes())
    step_index = 0
    error = ""
    clock = pygame.time.Clock()

    while step_index < len(STEPS):
        step = STEPS[step_index]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return 1
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                print("Dibatalkan, calibration.yaml tidak diubah.")
                return 1

            # Langkah tombol ditangkap dari event tekan tombol joystick.
            if step.key in ("arm", "estop", "horn") and event.type == pygame.JOYBUTTONDOWN:
                if step.key == "arm":
                    result.arm_button = event.button
                elif step.key == "estop":
                    if event.button == result.arm_button:
                        error = "Tombol itu sudah dipakai untuk ARM. Pilih tombol lain."
                        continue
                    result.estop_button = event.button
                else:  # horn
                    if event.button == result.arm_button:
                        error = "Tombol itu sudah dipakai untuk ARM. Pilih tombol lain."
                        continue
                    if event.button == result.estop_button:
                        error = "Tombol itu sudah dipakai untuk STOP DARURAT. Pilih tombol lain."
                        continue
                    result.horn_button = event.button
                error = ""
                step_index += 1
                continue

            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                error = self_capture(stick, step, result)
                if error == "":
                    step_index += 1

        screen.fill(BG)

        header = pygame.Rect(0, 0, WIDTH, 96)
        pygame.draw.rect(screen, PANEL, header)
        screen.blit(font_small.render(
            f"Langkah {step_index + 1} dari {len(STEPS)}   |   {stick.get_name()}",
            True, DIM), (40, 16))
        screen.blit(font_big.render(step.title, True, WHITE), (40, 40))
        screen.blit(font_small.render(step.hint, True, AMBER), (40, 72))

        draw_axes(screen, font_small, stick, result.rest, result, 130)
        draw_buttons(screen, font_small, stick, result,
                     130 + stick.get_numaxes() * 22 + 20)

        if error:
            screen.blit(font_small.render(error, True, RED), (48, HEIGHT - 56))
        screen.blit(font_small.render(
            "SPASI = rekam langkah ini    ESC = batal", True, DIM),
            (48, HEIGHT - 32))

        pygame.display.flip()
        clock.tick(60)

    shifter = run_shifter_wizard(screen, font_big, font, font_small, stick)

    calibration = {
        "joystick": {
            "index": stick.get_id(),
            "name": stick.get_name(),
            "num_axes": stick.get_numaxes(),
            "num_buttons": stick.get_numbuttons(),
        },
        "axes": {
            "steer": {
                "axis": result.steer_axis,
                "min": round(result.steer_min, 4),
                "center": round(result.rest[result.steer_axis], 4),
                "max": round(result.steer_max, 4),
            },
            "gas": {
                "axis": result.gas_axis,
                "released": round(result.rest[result.gas_axis], 4),
                "pressed": round(result.gas_pressed, 4),
            },
            "brake": {
                "axis": result.brake_axis,
                "released": round(result.rest[result.brake_axis], 4),
                "pressed": round(result.brake_pressed, 4),
            },
        },
        "buttons": {
            "arm": result.arm_button,
            "estop": result.estop_button,
            "horn": result.horn_button,
        },
    }

    if shifter.kind == "h_pattern":
        # Kunci -1 dipakai untuk posisi R, sejajar dengan konvensi gear di
        # rcground/wheel.py: -1 = R, 0 = N (tidak ada tombol aktif), 1..N = maju.
        h_buttons = dict(shifter.gear_buttons)
        if shifter.reverse_button is not None:
            h_buttons[-1] = shifter.reverse_button
        calibration["shifter"] = {
            "type": "h_pattern",
            "buttons": h_buttons,
        }
    elif shifter.kind == "sequential":
        calibration["shifter"] = {
            "type": "sequential",
            "up_button": shifter.up_button,
            "down_button": shifter.down_button,
        }
    # kind None (dilewati) -> kunci "shifter" TIDAK ditulis sama sekali,
    # supaya fallback perilaku lama di rcground/wheel.py tetap aktif.

    path = cfg.save_calibration(calibration)
    pygame.quit()

    print("\nKalibrasi selesai:")
    print(f"  stir  : axis {result.steer_axis}  "
          f"({result.steer_min:+.2f} .. {result.rest[result.steer_axis]:+.2f} "
          f".. {result.steer_max:+.2f})")
    print(f"  gas   : axis {result.gas_axis}  "
          f"(lepas {result.rest[result.gas_axis]:+.2f} -> injak {result.gas_pressed:+.2f})")
    print(f"  rem   : axis {result.brake_axis}  "
          f"(lepas {result.rest[result.brake_axis]:+.2f} -> injak {result.brake_pressed:+.2f})")
    print(f"  arm   : tombol {result.arm_button}")
    print(f"  stop  : tombol {result.estop_button}")
    print(f"  klakson: tombol {result.horn_button}")
    if shifter.kind == "h_pattern":
        gears = "  ".join(
            f"gigi {g}=tombol {b}" for g, b in sorted(shifter.gear_buttons.items())
        )
        print(f"  gigi  : H-pattern -- {gears}  R=tombol {shifter.reverse_button}")
    elif shifter.kind == "sequential":
        print(f"  gigi  : sequential -- naik=tombol {shifter.up_button}  "
              f"turun=tombol {shifter.down_button}")
    else:
        print("  gigi  : dilewati (pedal rem tetap berfungsi sebagai mundur)")
    print(f"\nDisimpan ke {path}")
    print("Sekarang jalankan:  python main.py")
    return 0


def self_capture(stick, step: Step, result: Result) -> str:
    """Rekam satu langkah. Kembalikan pesan error, atau string kosong bila sukses."""
    if step.key == "rest":
        result.rest = [stick.get_axis(i) for i in range(stick.get_numaxes())]
        return ""

    if step.key == "left":
        axis = detect_moved_axis(stick, result.rest, exclude=set())
        if axis is None:
            return "Tidak ada axis yang bergerak cukup jauh. Putar stir sampai mentok."
        result.steer_axis = axis
        result.steer_min = stick.get_axis(axis)
        return ""

    if step.key == "right":
        if result.steer_axis is None:
            return "Axis stir belum dikenali."
        value = stick.get_axis(result.steer_axis)
        if abs(value - result.steer_min) < MOVE_THRESHOLD:
            return "Stir tampaknya belum diputar ke arah berlawanan."
        result.steer_max = value
        return ""

    if step.key == "gas":
        axis = detect_moved_axis(stick, result.rest, exclude={result.steer_axis})
        if axis is None:
            return "Pedal gas tidak terdeteksi. Injak sampai mentok lalu tekan SPASI."
        result.gas_axis = axis
        result.gas_pressed = stick.get_axis(axis)
        return ""

    if step.key == "brake":
        axis = detect_moved_axis(
            stick, result.rest, exclude={result.steer_axis, result.gas_axis}
        )
        if axis is None:
            return ("Pedal rem tidak terdeteksi. Kalau PXN diset mode 'combined "
                    "pedal', ubah saklarnya ke mode pedal terpisah lalu ulangi.")
        result.brake_axis = axis
        result.brake_pressed = stick.get_axis(axis)
        return ""

    return ""


if __name__ == "__main__":
    raise SystemExit(main())
