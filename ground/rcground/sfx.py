"""Efek suara (gas, klakson, arm) untuk ground station.

Semua suara diputar di SISI DARAT, bukan di mobil -- ESP32 tidak punya
speaker. Ini murni umpan balik untuk pengemudi (dan penonton di sekitar
laptop/LattePanda), sama sekali tidak mempengaruhi perintah yang dikirim ke
mobil.

Prinsip desain paling penting di berkas ini: SFX TIDAK BOLEH PERNAH
menjatuhkan aplikasi. LattePanda di lapangan sering headless / tanpa
speaker terpasang, manifest.yaml atau berkas mp3 bisa hilang/korup saat
disalin, dan pengguna mungkin sengaja mematikan suara lewat config.yaml.
Semua kondisi itu harus berakhir sebagai "SfxEngine diam", bukan traceback.
Karena itu SETIAP method publik dibungkus supaya aman dipanggil kapan pun,
dan flag `self._enabled` dicek di awal masing-masing.

Pack aktif per kategori (gas/horn/arm) bisa diganti on-the-fly dari main.py
(tombol G/N/M, lihat main.py), dan indeksnya disimpan balik ke config.yaml
lewat rcground.config.save_sfx_packs supaya pilihan pengguna bertahan ke
sesi berikutnya.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

try:
    import pygame
except ImportError:  # pragma: no cover -- pygame selalu ada di proyek ini
    pygame = None  # type: ignore[assignment]


CATEGORIES = ("gas", "horn", "arm")

# Pemetaan intensitas pedal (0..1) ke volume suara gas. Batas bawah 0.4
# (bukan 0.0) supaya suara mesin tetap terdengar "hidup" bahkan saat pedal
# baru sedikit diinjak -- gas 0.0 sendiri tidak memicu playback sama sekali
# (lihat update_gas), jadi rentang ini hanya berlaku selama mesin benar-benar
# berbunyi.
GAS_VOLUME_MIN = 0.4
GAS_VOLUME_MAX = 1.0

FADE_MS = 120   # fade out halus saat gas berhenti -- lihat update_gas


def _sfx_root() -> Path:
    """Cari folder assets/sfx/, aman baik sebagai skrip maupun exe frozen.

    Ini SENGAJA berbeda dari pola sys.executable di rcground/config.py.
    config.yaml dan calibration.yaml harus bisa diedit pengguna, jadi mereka
    ditaruh DI SEBELAH exe (lihat komentar panjang di config.py soal
    sys.executable). assets/sfx/ sebaliknya tidak pernah perlu diedit
    pengguna, jadi build_exe.py membundelnya LANGSUNG KE DALAM exe lewat
    --add-data (lihat build_exe.py). PyInstaller mode --onefile mengekstrak
    data yang dibundel seperti itu ke folder sementara sys._MEIPASS saat exe
    dijalankan -- BUKAN ke folder tempat exe itu berada. Karena itu base path
    yang benar untuk assets/sfx/ adalah sys._MEIPASS kalau ada (mode frozen),
    dan folder ground/ (dua tingkat di atas berkas ini) kalau tidak (mode
    skrip biasa, `python main.py`).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets" / "sfx"
    return Path(__file__).resolve().parent.parent / "assets" / "sfx"


class _Pack:
    """Satu berkas suara yang sudah dimuat: Sound pygame + judul dari manifest."""

    __slots__ = ("sound", "title")

    def __init__(self, sound, title: str) -> None:
        self.sound = sound
        self.title = title


class SfxEngine:
    """Muat dan mainkan seluruh efek suara gas/klakson/arm.

    Kalau inisialisasi audio gagal (atau sfx.enabled: false di config.yaml),
    seluruh instance jatuh ke mode no-op diam-diam -- lihat `_enabled`.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = False
        self._packs: dict[str, list[_Pack]] = {c: [] for c in CATEGORIES}
        self._index: dict[str, int] = {c: 0 for c in CATEGORIES}

        # Channel terpisah per kategori supaya gas/klakson/arm bisa tumpang
        # tindih tanpa saling memotong satu sama lain (mis. klakson dibunyikan
        # sambil gas masih menderu). pygame.mixer.Sound.play() tanpa channel
        # eksplisit akan mengambil channel bebas mana pun, yang membuat
        # fadeout/stop per kategori tidak bisa diandalkan.
        self._channel_gas = None
        self._channel_horn = None
        self._channel_arm = None

        self._gas_active = False

        if not enabled:
            # Dimatikan dengan sengaja lewat config -- bukan error, jadi
            # TIDAK ada peringatan dicetak.
            return

        if pygame is None:
            print("SFX: modul pygame tidak tersedia, suara dimatikan.")
            return

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception as exc:  # noqa: BLE001
            print(f"SFX: gagal menginisialisasi audio ({exc}), suara dimatikan.")
            return

        try:
            self._load_all()
        except Exception as exc:  # noqa: BLE001
            print(f"SFX: gagal memuat berkas suara ({exc}), suara dimatikan.")
            self._packs = {c: [] for c in CATEGORIES}
            return

        # Kalau manifest ada tapi ternyata kosong (0 berkas termuat) untuk
        # semua kategori, tidak ada gunanya menganggap engine ini "aktif".
        if not any(self._packs[c] for c in CATEGORIES):
            print("SFX: tidak ada berkas suara termuat, suara dimatikan.")
            return

        try:
            self._channel_gas = pygame.mixer.Channel(0)
            self._channel_horn = pygame.mixer.Channel(1)
            self._channel_arm = pygame.mixer.Channel(2)
        except Exception as exc:  # noqa: BLE001
            print(f"SFX: gagal menyiapkan channel audio ({exc}), suara dimatikan.")
            return

        self._enabled = True

    # -- pemuatan ----------------------------------------------------------
    def _load_all(self) -> None:
        root = _sfx_root()
        manifest_path = root / "manifest.yaml"
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = yaml.safe_load(handle) or {}

        for category in CATEGORIES:
            entries = manifest.get(category) or []
            packs: list[_Pack] = []
            for entry in entries:
                filename = entry.get("file")
                title = entry.get("title", filename or "?")
                if not filename:
                    continue
                path = root / category / filename
                try:
                    sound = pygame.mixer.Sound(str(path))
                except Exception as exc:  # noqa: BLE001
                    # Satu berkas korup/hilang tidak boleh menggagalkan
                    # seluruh kategori -- lewati saja, pack yang lain tetap
                    # bisa dipakai.
                    print(f"SFX: gagal memuat {path} ({exc}), dilewati.")
                    continue
                packs.append(_Pack(sound, title))
            self._packs[category] = packs

    # -- pack aktif ----------------------------------------------------------
    def _clamp_index(self, category: str) -> None:
        count = len(self._packs[category])
        if count == 0:
            self._index[category] = 0
        else:
            self._index[category] %= count

    def set_pack(self, category: str, index: int) -> None:
        """Set indeks pack secara langsung (dipakai saat memuat config.yaml saat start).

        Di-clamp aman kalau index di luar jangkauan -- config.yaml lama atau
        yang diedit manual tidak boleh membuat aplikasi crash.
        """
        if category not in self._packs:
            return
        self._index[category] = int(index)
        self._clamp_index(category)

    def next_pack(self, category: str) -> None:
        if category not in self._packs or not self._packs[category]:
            return
        self._index[category] += 1
        self._clamp_index(category)

    def prev_pack(self, category: str) -> None:
        if category not in self._packs or not self._packs[category]:
            return
        self._index[category] -= 1
        self._clamp_index(category)

    def pack_index(self, category: str) -> int:
        return self._index.get(category, 0)

    def pack_label(self, category: str) -> str:
        """Label singkat "i/N Judul" untuk ditampilkan di HUD."""
        packs = self._packs.get(category, [])
        if not packs:
            return "-- (tidak ada)"
        index = self._index.get(category, 0) % len(packs)
        title = packs[index].title
        return f"{index + 1}/{len(packs)} {title}"

    def _current(self, category: str) -> "_Pack | None":
        packs = self._packs.get(category, [])
        if not packs:
            return None
        index = self._index.get(category, 0) % len(packs)
        return packs[index]

    # -- arm -----------------------------------------------------------------
    def play_arm(self) -> None:
        """Putar suara arm SEKALI. Dipanggil tepat pada transisi disarmed->armed."""
        if not self._enabled:
            return
        pack = self._current("arm")
        if pack is None:
            return
        # Hentikan pemutaran arm sebelumnya (kalau ada, mis. arm-disarm-arm
        # cepat) supaya tidak menumpuk/overlap -- lalu mulai dari awal.
        self._channel_arm.stop()
        self._channel_arm.play(pack.sound)

    # -- gas -------------------------------------------------------------
    def update_gas(self, intensity: float, active: bool) -> None:
        """Dipanggil tiap iterasi loop utama.

        intensity: 0..1, bacaan pedal gas MENTAH (bukan output motor biner --
        lihat catatan di config.py/main.py soal MOTOR_BINARY). active: True
        selama mobil armed dan tidak failsafe.
        """
        if not self._enabled:
            return
        pack = self._current("gas")
        if pack is None:
            return

        if active and intensity > 0.0:
            intensity = max(0.0, min(1.0, intensity))
            volume = GAS_VOLUME_MIN + intensity * (GAS_VOLUME_MAX - GAS_VOLUME_MIN)
            if not self._gas_active:
                self._channel_gas.play(pack.sound, loops=-1)
                self._gas_active = True
            self._channel_gas.set_volume(volume)
        elif self._gas_active:
            # Fade out halus alih-alih stop mendadak -- stop() langsung
            # membuat suara terputus kasar begitu pedal dilepas.
            self._channel_gas.fadeout(FADE_MS)
            self._gas_active = False

    # -- klakson -----------------------------------------------------------
    def play_horn(self) -> None:
        """Putar suara klakson SEKALI dari awal sampai selesai.

        Dipanggil pada TIAP tekan klakson (edge, bukan level -- lihat
        horn_edge di wheel.py dan keyboard_horn_edge di main.py), seperti
        klakson mobil sungguhan yang di-"pip" sekali per tekan. Kalau
        ditekan lagi sebelum suara sebelumnya selesai, hentikan yang lama
        dan mulai lagi dari awal -- tidak menumpuk suara. Bergaya sama
        seperti play_arm() di atas.
        """
        if not self._enabled:
            return
        pack = self._current("horn")
        if pack is None:
            return
        self._channel_horn.stop()
        self._channel_horn.play(pack.sound)
