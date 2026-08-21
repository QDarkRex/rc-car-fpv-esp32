"""Ground station RC Car — aplikasi utama.

Membaca stir PXN, menerapkan kurva/limit, mengirim perintah ke mobil 50 kali
per detik, dan menggambar video FPV beserta HUD.

Jalankan:
    python main.py                     # normal
    python main.py --car 127.0.0.1     # uji dengan fake_car.py di mesin ini
    python main.py --cam http://127.0.0.1:8080/stream   # uji dgn fake_cam.py
    python main.py --no-video          # tanpa kamera
    python main.py --keyboard          # paksa kendali keyboard

Tombol:
    SPASI   arm / disarm
    E       stop darurat (langsung disarm)
    [ ]     geser trim stir kiri / kanan
    F5      simpan trim ke config.yaml
    F11     layar penuh
    ESC     keluar
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygame

from rcground import config as cfg
from rcground.hud import Hud, HudContext
from rcground.link import Link
from rcground.video import MjpegStream
from rcground.wheel import KeyboardWheel, Wheel

TRIM_STEP = 0.005
MESSAGE_DURATION = 2.5
ARM_THROTTLE_LIMIT = 0.02   # gas harus benar-benar netral saat arming


class GroundStation:
    def __init__(self, args) -> None:
        self.config = cfg.load_config()
        self.calibration = cfg.load_calibration()

        if args.car:
            self.config["network"]["car_ip"] = args.car
            # Saat menguji ke alamat spesifik, broadcast hanya menambah bising.
            self.config["network"]["broadcast"] = args.car
        if args.cam:
            self.config["camera"]["stream_url"] = args.cam

        self.disarm_on_link_loss = bool(
            self.config["network"].get("disarm_on_link_loss", True)
        )
        self.rate = float(self.config["network"].get("control_rate_hz", 50))
        self.period = 1.0 / max(1.0, self.rate)

        pygame.init()
        pygame.display.set_caption("RC Car — Ground Station")
        display = self.config.get("display", {})
        self.window_size = (int(display.get("width", 960)), int(display.get("height", 720)))
        self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self.fullscreen = False

        self.hud = Hud()
        self.link = Link(self.config)

        self.wheel = self._make_wheel(args.keyboard)

        self.video: MjpegStream | None = None
        if not args.no_video:
            camera = self.config.get("camera", {})
            self.video = MjpegStream(
                str(camera.get("stream_url")), float(camera.get("timeout_s", 3.0))
            ).start()

        self.armed = False
        self.estop_latched = False
        self.running = True
        self.message = ""
        self.message_until = 0.0

        self._frame_surface: pygame.Surface | None = None
        self._frame_id_shown = -1
        self._scaled_cache: tuple = (None, None)

    # -- penyiapan -------------------------------------------------------
    def _make_wheel(self, force_keyboard: bool):
        if force_keyboard:
            self._notify("Mode keyboard dipaksa lewat --keyboard")
            return KeyboardWheel(self.config)

        wheel = Wheel(self.calibration, self.config)
        if not wheel.connected:
            print("Stir tidak terdeteksi - memakai kendali keyboard.")
            print("Colok PXN V9, lalu jalankan calibrate.py sebelum main.py.")
            return KeyboardWheel(self.config)

        if not self.calibration:
            print(f"Stir '{wheel.name}' terdeteksi, tetapi calibration.yaml belum ada.")
            print("Nilai axis default dipakai dan kemungkinan besar SALAH.")
            print("Jalankan dulu:  python calibrate.py")
        return wheel

    def _notify(self, text: str) -> None:
        self.message = text
        self.message_until = time.monotonic() + MESSAGE_DURATION

    # -- arming ----------------------------------------------------------
    def _request_arm_toggle(self, throttle_input: float, gear: int = 0) -> None:
        if self.armed:
            self._disarm("Disarmed")
            return

        # Tiga syarat sebelum motor boleh hidup. Semuanya penting.
        if not self.link.locked:
            self._notify("Tidak bisa arm: mobil belum menjawab")
            return
        if not self.link.connected:
            self._notify("Tidak bisa arm: tautan sedang putus")
            return
        if abs(throttle_input) > ARM_THROTTLE_LIMIT:
            self._notify("Tidak bisa arm: lepaskan pedal dulu")
            return
        shifter_cfg = self.config.get("shifter", {})
        if (
            getattr(self.wheel, "shifter_enabled", False)
            and bool(shifter_cfg.get("require_neutral_to_arm", True))
            and gear != 0
        ):
            self._notify("Tidak bisa arm: masukkan ke gigi N")
            return

        self.armed = True
        self.estop_latched = False
        self._notify("ARMED — mobil siap bergerak")

    def _disarm(self, reason: str) -> None:
        if self.armed:
            self._notify(reason)
        self.armed = False
        self.wheel.reset_throttle()
        self.wheel.reset_gear()

    def _emergency_stop(self) -> None:
        self.estop_latched = True
        self.armed = False
        self.wheel.reset_throttle()
        self.wheel.reset_gear()
        self._notify("STOP DARURAT — tekan SPASI untuk arm ulang")

    # -- event -----------------------------------------------------------
    def _handle_events(self, throttle_input: float, gear: int = 0) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.VIDEORESIZE:
                self.window_size = (event.w, event.h)
                self._scaled_cache = (None, None)

            elif event.type == pygame.JOYDEVICEREMOVED:
                # Stir dicabut saat armed adalah kondisi berbahaya. Reconnect
                # di sini aman; event ADDED yang dihasilkan saat joystick
                # dibuka kembali akan diabaikan bila perangkat sudah aktif.
                self._disarm("Perangkat kendali dilepas — disarmed")
                self.wheel.reconnect()

            elif event.type == pygame.JOYDEVICEADDED:
                # pygame.joystick.init()/Joystick.init() sendiri dapat
                # menghasilkan JOYDEVICEADDED. Memanggil reconnect tanpa
                # syarat di sini menciptakan loop: reconnect -> ADDED ->
                # reconnect, yang menahan loop kontrol hingga sekitar 6 Hz.
                if not self.wheel.connected:
                    self._disarm("Perangkat kendali tersambung — disarmed")
                    self.wheel.reconnect()

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_SPACE:
                    self._request_arm_toggle(throttle_input, gear)
                elif event.key == pygame.K_e:
                    self._emergency_stop()
                elif event.key == pygame.K_LEFTBRACKET:
                    self.wheel.adjust_trim(-TRIM_STEP)
                    self._notify(f"Trim {self.wheel.trim:+.3f}")
                elif event.key == pygame.K_RIGHTBRACKET:
                    self.wheel.adjust_trim(+TRIM_STEP)
                    self._notify(f"Trim {self.wheel.trim:+.3f}")
                elif event.key == pygame.K_F5:
                    self._save_trim()
                elif event.key == pygame.K_F11:
                    self._toggle_fullscreen()

    def _save_trim(self) -> None:
        try:
            cfg.save_trim(self.wheel.trim)
            self._notify(f"Trim {self.wheel.trim:+.3f} disimpan ke config.yaml")
        except (OSError, ValueError) as exc:
            self._notify(f"Gagal menyimpan trim: {exc}")

    def _toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode(self.window_size, flags)
        self._scaled_cache = (None, None)

    # -- tampilan --------------------------------------------------------
    def _decode_latest_frame(self) -> None:
        if self.video is None:
            return
        jpeg, frame_id = self.video.latest()
        if jpeg is None or frame_id == self._frame_id_shown:
            return
        try:
            surface = pygame.image.load(io.BytesIO(jpeg), "frame.jpg")
        except pygame.error:
            # Frame rusak di tengah jalan bukan alasan untuk menjatuhkan
            # aplikasi; frame berikutnya tinggal 30-an milidetik lagi.
            return
        self._frame_surface = surface.convert()
        self._frame_id_shown = frame_id
        self._scaled_cache = (None, None)

    def _blit_video(self) -> bool:
        if self._frame_surface is None:
            return False

        screen_w, screen_h = self.screen.get_size()
        cached_key, cached_surface = self._scaled_cache
        key = (self._frame_id_shown, screen_w, screen_h)
        if cached_key != key:
            frame_w, frame_h = self._frame_surface.get_size()
            scale = min(screen_w / frame_w, screen_h / frame_h)
            size = (max(1, int(frame_w * scale)), max(1, int(frame_h * scale)))
            cached_surface = pygame.transform.smoothscale(self._frame_surface, size)
            self._scaled_cache = (key, cached_surface)

        self.screen.fill((10, 11, 14))
        rect = cached_surface.get_rect(center=(screen_w // 2, screen_h // 2))
        self.screen.blit(cached_surface, rect)
        return True

    def _build_context(self, state, throttle_out: float, brake_out: float) -> HudContext:
        telemetry = self.link.telemetry
        return HudContext(
            steer=state.steer,
            throttle=throttle_out,
            gas=state.gas,
            brake=state.brake,
            brake_out=brake_out,
            gear=state.gear,
            gear_label=state.gear_label,
            trim=self.wheel.trim,
            armed=self.armed and self.link.connected,
            failsafe=(telemetry.failsafe if telemetry else False) or not self.link.connected,
            link_connected=self.link.connected,
            link_locked=self.link.locked,
            wheel_connected=self.wheel.connected,
            wheel_name=self.wheel.name,
            input_source=state.source,
            rtt_ms=self.link.rtt_ms,
            video_fps=self.video.fps if self.video else 0.0,
            telemetry_hz=self.link.telemetry_hz,
            rssi=telemetry.rssi if telemetry else None,
            vbat=telemetry.vbat if telemetry else None,
            low_batt=telemetry.low_batt if telemetry else False,
            uptime_ms=telemetry.uptime_ms if telemetry else 0,
            target=self.link.target_description,
            video_ok=bool(self.video and self.video.connected),
            video_error=self.video.error if self.video else "video dimatikan",
            max_forward=float(self.config["throttle"].get("max_forward", 0.7)),
            message=self.message if time.monotonic() < self.message_until else "",
        )

    # -- loop utama ------------------------------------------------------
    def run(self) -> int:
        print(f"Mengirim ke {self.link.target_description} pada {self.rate:.0f} Hz")
        if self.video:
            print(f"Video: {self.config['camera']['stream_url']}")

        next_tick = time.monotonic()
        last_time = next_tick
        announced_lock = False

        while self.running:
            now = time.monotonic()
            dt = min(0.1, now - last_time)
            last_time = now

            state = self.wheel.read(dt)
            self._handle_events(state.throttle, state.gear)

            if state.arm_edge:
                self._request_arm_toggle(state.throttle, state.gear)
            if state.estop_held:
                self._emergency_stop()

            self.link.poll()

            if self.link.locked and not announced_lock:
                announced_lock = True
                print(f"Mobil ditemukan di {self.link.target_description} - "
                      "beralih ke unicast")
                self._notify("Mobil ditemukan — tekan SPASI untuk arm")

            # Tautan putus saat armed melepas arming di sisi darat juga, supaya
            # pemulihan WiFi tidak langsung menghidupkan motor. Bisa dimatikan
            # lewat network.disarm_on_link_loss -- lihat catatannya di
            # config.yaml, dan pastikan sepasang dengan FAILSAFE_ENABLED di
            # firmware supaya kedua sisi sepakat.
            if (
                self.disarm_on_link_loss
                and self.armed
                and not self.link.connected
                and self.link.rtt_ms is not None
            ):
                self._disarm("Tautan putus — disarmed")

            throttle_out = state.throttle if self.armed else 0.0
            brake_out = state.brake_out if self.armed else 0.0
            if not self.armed:
                self.wheel.reset_throttle()

            self.link.send(state.steer, throttle_out, self.armed, brake_out)

            self._decode_latest_frame()
            context = self._build_context(state, throttle_out, brake_out)
            if not self._blit_video():
                self.hud.draw_no_video(self.screen, context)
            self.hud.draw(self.screen, context, dt)
            pygame.display.flip()

            next_tick += self.period
            sleep = next_tick - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                # Ketinggalan jadwal: setel ulang alih-alih mengejar,
                # supaya tidak terjadi ledakan paket beruntun.
                next_tick = time.monotonic()

        self.shutdown()
        return 0

    def shutdown(self) -> None:
        print("\nMenutup - mengirim perintah netral...")
        # Beberapa paket disarm berturut-turut supaya mobil pasti berhenti
        # meskipun sebagian paket hilang.
        for _ in range(10):
            self.link.send(0.0, 0.0, False)
            time.sleep(0.01)
        if self.video:
            self.video.stop()
        self.link.close()
        pygame.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ground station RC Car")
    parser.add_argument("--car", metavar="IP", help="timpa IP mobil dari config.yaml")
    parser.add_argument("--cam", metavar="URL", help="timpa URL stream dari config.yaml")
    parser.add_argument("--no-video", action="store_true", help="jalan tanpa kamera")
    parser.add_argument("--keyboard", action="store_true", help="paksa kendali keyboard")
    args = parser.parse_args()

    try:
        station = GroundStation(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Gagal memulai: {type(exc).__name__}: {exc}")
        return 1

    try:
        return station.run()
    except KeyboardInterrupt:
        station.shutdown()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
