"""Pembacaan stir PXN V9 dan pemrosesan input menjadi perintah kendali.

Semua tuning (deadzone, expo, trim, batas kecepatan, slew rate) diterapkan di
sini -- di sisi darat -- sehingga bisa diubah tanpa flash ulang ESP32.

Kalibrasi mentah (indeks axis dan nilai ujung-ujungnya) datang dari
calibration.yaml yang dihasilkan calibrate.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame


# ---------------------------------------------------------------- utilitas

def apply_deadzone(value: float, deadzone: float) -> float:
    """Nolkan sekitar tengah, lalu regangkan sisanya kembali ke rentang penuh.

    Tanpa peregangan ini, output akan melompat dari 0 ke nilai deadzone begitu
    stir keluar dari zona mati.
    """
    if deadzone <= 0.0:
        return value
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    scaled = (magnitude - deadzone) / (1.0 - deadzone)
    return math.copysign(min(1.0, scaled), value)


def apply_expo(value: float, expo: float) -> float:
    """Kurva expo standar RC: halus di tengah, tetap penuh di ujung.

    expo=0 menghasilkan respons linear; expo=1 menghasilkan kurva kubik penuh.
    """
    expo = max(0.0, min(1.0, expo))
    return (1.0 - expo) * value + expo * value * value * value


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_bipolar(raw: float, low: float, center: float, high: float) -> float:
    """Petakan axis dua arah (stir) ke -1..1, menghormati titik tengah kalibrasi."""
    if raw >= center:
        span = high - center
        return 0.0 if abs(span) < 1e-6 else _clamp((raw - center) / span, -1.0, 1.0)
    span = center - low
    return 0.0 if abs(span) < 1e-6 else _clamp((raw - center) / span, -1.0, 1.0)


def _normalize_unipolar(raw: float, released: float, pressed: float) -> float:
    """Petakan axis pedal ke 0..1.

    Karena nilai saat pedal dilepas dan saat diinjak penuh diambil apa adanya
    ketika kalibrasi, pedal yang axis-nya terbalik tertangani otomatis tanpa
    perlu flag invert terpisah.
    """
    span = pressed - released
    if abs(span) < 1e-6:
        return 0.0
    return _clamp((raw - released) / span, 0.0, 1.0)


# ---------------------------------------------------------------- keadaan

@dataclass
class WheelState:
    steer: float = 0.0          # -1..1 setelah seluruh pemrosesan
    throttle: float = 0.0       # -1..1 setelah seluruh pemrosesan
    raw_steer: float = 0.0      # -1..1 sebelum expo/trim/limit
    gas: float = 0.0            # 0..1
    brake: float = 0.0          # 0..1, bacaan pedal rem mentah (setelah deadzone)
    brake_out: float = 0.0      # 0..1, nilai brake yang benar-benar dikirim ke mobil
    gear: int = 0                # -1 = R, 0 = N, 1..N = gigi maju
    gear_label: str = "N"        # "R", "N", "1".."6"
    arm_edge: bool = False      # True hanya pada frame tombol arm ditekan
    estop_held: bool = False
    horn_held: bool = False     # True selama tombol klakson pada stir ditahan
    connected: bool = False
    source: str = "none"
    buttons: dict = field(default_factory=dict)


# ---------------------------------------------------------------- pembaca

class Wheel:
    """Membaca stir fisik lewat pygame dan menerapkan seluruh kurva/limit."""

    def __init__(self, calibration: dict, tuning: dict) -> None:
        self.calibration = calibration or {}
        self.tuning = tuning
        self.joystick = None
        self.name = "(tidak ada)"

        self._prev_arm = False
        self._throttle_out = 0.0
        self._trim = float(tuning.get("steering", {}).get("trim", 0.0))

        # -- gigi --------------------------------------------------------
        # Fallback WAJIB: kalau calibration.yaml tidak punya bagian shifter
        # (belum dikalibrasi ulang, atau tuas gigi tidak dipakai), shifter
        # dianggap tidak aktif dan perilaku LAMA dipertahankan persis --
        # pedal rem tetap dipetakan menjadi mundur, tanpa gigi sama sekali.
        self._shifter_cal = self.calibration.get("shifter") or {}
        shifter_tuning = tuning.get("shifter", {})
        self.shifter_enabled = bool(
            shifter_tuning.get("enabled", True)
        ) and bool(self._shifter_cal)
        self._gear_ratios = list(shifter_tuning.get("gear_ratios", []))
        self._seq_gear = 0          # gigi tersimpan untuk tuas sequential
        self._prev_up = False
        self._prev_down = False

        self._open()

    # -- gigi --------------------------------------------------------------
    def reset_gear(self) -> None:
        """Kembalikan gigi sequential ke N -- dipanggil saat disarm / estop."""
        self._seq_gear = 0

    @staticmethod
    def _gear_label(gear: int) -> str:
        if gear < 0:
            return "R"
        if gear == 0:
            return "N"
        return str(gear)

    def _read_gear(self, js) -> int:
        """Baca posisi gigi dari tuas, sesuai jenisnya (h_pattern / sequential)."""
        shifter_type = self._shifter_cal.get("type")

        if shifter_type == "h_pattern":
            buttons_map = self._shifter_cal.get("buttons", {})
            for key, idx in buttons_map.items():
                if idx is None:
                    continue
                idx = int(idx)
                if 0 <= idx < js.get_numbuttons() and js.get_button(idx):
                    return int(key)
            return 0   # tidak ada tombol aktif = N

        if shifter_type == "sequential":
            up_idx = self._shifter_cal.get("up_button")
            down_idx = self._shifter_cal.get("down_button")

            def pressed(idx) -> bool:
                if idx is None:
                    return False
                idx = int(idx)
                return 0 <= idx < js.get_numbuttons() and js.get_button(idx)

            up_now = pressed(up_idx)
            down_now = pressed(down_idx)
            max_gear = len(self._gear_ratios) if self._gear_ratios else 1

            if up_now and not self._prev_up:
                self._seq_gear = min(max_gear, self._seq_gear + 1)
            if down_now and not self._prev_down:
                self._seq_gear = max(-1, self._seq_gear - 1)

            self._prev_up = up_now
            self._prev_down = down_now
            return self._seq_gear

        return 0

    # -- koneksi ---------------------------------------------------------
    def _open(self) -> None:
        if not pygame.joystick.get_init():
            pygame.joystick.init()

        joy_cfg = self.calibration.get("joystick", {})
        wanted_index = int(joy_cfg.get("index", 0))
        wanted_name = joy_cfg.get("name")

        count = pygame.joystick.get_count()
        if count == 0:
            return

        index = wanted_index
        # Kalau nama tercatat, cocokkan nama lebih dulu. Ini penting saat ada
        # dua unit PXN V9 terpasang dan urutan enumerasinya berubah antar boot.
        if wanted_name:
            for i in range(count):
                if pygame.joystick.Joystick(i).get_name() == wanted_name:
                    index = i
                    break
        if index >= count:
            index = 0

        self.joystick = pygame.joystick.Joystick(index)
        self.joystick.init()
        self.name = self.joystick.get_name()

    def reconnect(self) -> None:
        """Panggil setelah event JOYDEVICEADDED / JOYDEVICEREMOVED."""
        self.joystick = None
        pygame.joystick.quit()
        pygame.joystick.init()
        self._open()

    @property
    def connected(self) -> bool:
        return self.joystick is not None and self.joystick.get_init()

    # -- trim ------------------------------------------------------------
    @property
    def trim(self) -> float:
        return self._trim

    def adjust_trim(self, delta: float) -> None:
        self._trim = _clamp(self._trim + delta, -0.5, 0.5)

    # -- pembacaan -------------------------------------------------------
    def read(self, dt: float) -> WheelState:
        state = WheelState(source="wheel")
        if not self.connected:
            self._throttle_out = 0.0
            return state

        js = self.joystick
        state.connected = True

        axes = self.calibration.get("axes", {})
        buttons_cfg = self.calibration.get("buttons", {})

        def axis(idx: int) -> float:
            return js.get_axis(idx) if 0 <= idx < js.get_numaxes() else 0.0

        def button(idx) -> bool:
            if idx is None:
                return False
            idx = int(idx)
            return js.get_button(idx) if 0 <= idx < js.get_numbuttons() else False

        # --- stir
        steer_cal = axes.get("steer", {})
        raw_steer = _normalize_bipolar(
            axis(int(steer_cal.get("axis", 0))),
            float(steer_cal.get("min", -1.0)),
            float(steer_cal.get("center", 0.0)),
            float(steer_cal.get("max", 1.0)),
        )

        # --- pedal
        gas_cal = axes.get("gas", {})
        brake_cal = axes.get("brake", {})
        gas = _normalize_unipolar(
            axis(int(gas_cal.get("axis", 1))),
            float(gas_cal.get("released", -1.0)),
            float(gas_cal.get("pressed", 1.0)),
        )
        brake = _normalize_unipolar(
            axis(int(brake_cal.get("axis", 2))),
            float(brake_cal.get("released", -1.0)),
            float(brake_cal.get("pressed", 1.0)),
        )

        arm_now = button(buttons_cfg.get("arm"))
        state.arm_edge = arm_now and not self._prev_arm
        self._prev_arm = arm_now
        state.estop_held = button(buttons_cfg.get("estop"))
        # .get("horn") aman kembalikan None kalau calibration.yaml lama belum
        # punya kunci ini (pengguna belum kalibrasi ulang lewat calibrate.py)
        # -- dan button(None) di atas sudah menangani None -> False.
        state.horn_held = button(buttons_cfg.get("horn"))
        state.buttons = {i: js.get_button(i) for i in range(js.get_numbuttons())}

        gear = self._read_gear(js) if self.shifter_enabled else 0

        state.raw_steer = raw_steer
        state.gas = gas
        state.brake = brake
        state.gear = gear
        state.gear_label = self._gear_label(gear)
        (
            state.steer,
            state.throttle,
            state.brake_out,
        ) = self._process(raw_steer, gas, brake, gear, dt)
        return state

    # -- pemrosesan kurva ------------------------------------------------
    def _process(
        self, raw_steer: float, gas: float, brake: float, gear: int, dt: float
    ) -> tuple:
        st = self.tuning.get("steering", {})
        th = self.tuning.get("throttle", {})

        # Stir: deadzone -> expo -> invert -> trim -> batas sudut
        steer = apply_deadzone(raw_steer, float(st.get("deadzone", 0.03)))
        steer = apply_expo(steer, float(st.get("expo", 0.30)))
        if st.get("invert", False):
            steer = -steer
        steer = _clamp(steer + self._trim, -1.0, 1.0)
        steer *= float(st.get("max_angle", 1.0))
        steer = _clamp(steer, -1.0, 1.0)

        if self.shifter_enabled:
            target, brake_out = self._process_geared(gas, brake, gear, th)
        else:
            # Perilaku LAMA: pedal rem dipetakan menjadi mundur, tidak ada
            # gigi sama sekali. Dipertahankan persis supaya pengguna yang
            # belum kalibrasi ulang tuas gigi tidak menemukan mobilnya
            # berubah perilaku begitu saja.
            gas_z = apply_deadzone(gas, float(th.get("deadzone", 0.05)))
            brake_z = apply_deadzone(brake, float(th.get("deadzone", 0.05)))
            net = apply_expo(gas_z - brake_z, float(th.get("expo", 0.40)))
            if net >= 0.0:
                target = net * float(th.get("max_forward", 0.70))
            else:
                target = net * float(th.get("max_reverse", 0.50))
            brake_out = 0.0

        # Slew rate: batasi seberapa cepat gas boleh berubah. Ini mencegah
        # sentakan arus yang menjatuhkan tegangan pada paket 4S kecil.
        slew = float(th.get("slew_rate", 3.0))
        if slew > 0.0 and dt > 0.0:
            max_delta = slew * dt
            self._throttle_out += _clamp(
                target - self._throttle_out, -max_delta, max_delta
            )
        else:
            self._throttle_out = target

        return steer, _clamp(self._throttle_out, -1.0, 1.0), brake_out

    def _process_geared(self, gas: float, brake: float, gear: int, th: dict) -> tuple:
        """Hitung throttle & rem saat state machine gigi aktif.

        N: throttle selalu 0 apa pun pedalnya. R: gas menghasilkan throttle
        negatif dibatasi max_reverse. Gigi maju n: gas menghasilkan throttle
        positif dibatasi gear_ratios[n-1] * max_forward. Pedal rem SELALU
        menghasilkan brake 0..1, tidak pernah menjadi mundur, di gigi mana pun.
        """
        gas_z = apply_deadzone(gas, float(th.get("deadzone", 0.05)))
        gas_curve = apply_expo(gas_z, float(th.get("expo", 0.40)))

        if gear == 0:
            target = 0.0
        elif gear < 0:
            target = -gas_curve * float(th.get("max_reverse", 0.50))
        else:
            ratios = self._gear_ratios
            ratio = ratios[gear - 1] if 0 < gear <= len(ratios) else 1.0
            target = gas_curve * float(ratio) * float(th.get("max_forward", 0.70))

        br = self.tuning.get("brake", {})
        brake_out = apply_deadzone(brake, float(br.get("deadzone", 0.05)))
        brake_out = _clamp(brake_out * float(br.get("strength", 1.0)), 0.0, 1.0)

        return target, brake_out

    def reset_throttle(self) -> None:
        """Nolkan keadaan internal slew -- dipanggil saat disarm / estop."""
        self._throttle_out = 0.0


# ---------------------------------------------------------------- cadangan

class KeyboardWheel:
    """Kendali keyboard sebagai cadangan saat stir belum terpasang.

    Panah kiri/kanan = stir, panah atas/bawah = gas/mundur.
    Berguna untuk menguji link, HUD, dan failsafe tanpa hardware apa pun.
    """

    def __init__(self, tuning: dict) -> None:
        self.tuning = tuning
        self.name = "Keyboard (cadangan)"
        self._steer = 0.0
        self._throttle = 0.0
        self._trim = float(tuning.get("steering", {}).get("trim", 0.0))
        # Keyboard tidak punya tuas gigi -- selalu perilaku lama (pedal
        # bawah = mundur), sama seperti stir yang belum dikalibrasi ulang.
        self.shifter_enabled = False

    @property
    def connected(self) -> bool:
        return True

    @property
    def trim(self) -> float:
        return self._trim

    def adjust_trim(self, delta: float) -> None:
        self._trim = _clamp(self._trim + delta, -0.5, 0.5)

    def reconnect(self) -> None:
        pass

    def reset_throttle(self) -> None:
        self._throttle = 0.0

    def reset_gear(self) -> None:
        pass

    def read(self, dt: float) -> WheelState:
        keys = pygame.key.get_pressed()
        th = self.tuning.get("throttle", {})

        steer_target = 0.0
        if keys[pygame.K_LEFT]:
            steer_target -= 1.0
        if keys[pygame.K_RIGHT]:
            steer_target += 1.0

        # Kembali ke tengah sendiri, meniru per pada stir sungguhan.
        rate = 3.5 * dt
        if steer_target == 0.0:
            self._steer -= _clamp(self._steer, -rate, rate)
        else:
            self._steer = _clamp(self._steer + steer_target * rate, -1.0, 1.0)

        gas = 1.0 if keys[pygame.K_UP] else 0.0
        brake = 1.0 if keys[pygame.K_DOWN] else 0.0
        net = gas - brake
        limit = th.get("max_forward", 0.70) if net >= 0 else th.get("max_reverse", 0.50)
        target = net * float(limit)

        slew = float(th.get("slew_rate", 3.0))
        if slew > 0.0 and dt > 0.0:
            max_delta = slew * dt
            self._throttle += _clamp(target - self._throttle, -max_delta, max_delta)
        else:
            self._throttle = target

        return WheelState(
            steer=_clamp(self._steer + self._trim, -1.0, 1.0),
            throttle=_clamp(self._throttle, -1.0, 1.0),
            raw_steer=self._steer,
            gas=gas,
            brake=brake,
            connected=True,
            source="keyboard",
        )
