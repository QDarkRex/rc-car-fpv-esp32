"""Pemuatan dan penyimpanan berkas konfigurasi.

Ada dua berkas, sengaja dipisah:

  config.yaml       -- tuning yang Anda tulis dan baca sendiri (kurva gas,
                       deadzone, trim, limit, jaringan). Berisi komentar
                       penjelasan, jadi TIDAK PERNAH ditimpa otomatis kecuali
                       Anda menekan F5 untuk menyimpan trim.

  calibration.yaml  -- hasil calibrate.py: indeks axis dan nilai ujung stir.
                       Berkas mesin, aman ditulis ulang kapan pun.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

GROUND_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = GROUND_DIR / "config.yaml"
CALIBRATION_PATH = GROUND_DIR / "calibration.yaml"

DEFAULT_CONFIG: dict = {
    "network": {
        "car_ip": "192.168.137.50",
        "car_port": 4210,
        "broadcast": "192.168.137.255",
        "control_rate_hz": 50,
        "link_timeout_ms": 500,
    },
    "camera": {"stream_url": "http://192.168.137.60/stream", "timeout_s": 3.0},
    "steering": {
        "deadzone": 0.03,
        "trim": 0.0,
        "expo": 0.30,
        "max_angle": 1.0,
        "invert": False,
    },
    "throttle": {
        "deadzone": 0.05,
        "expo": 0.40,
        "max_forward": 0.70,
        "max_reverse": 0.50,
        "slew_rate": 3.0,
    },
    "shifter": {
        "enabled": True,
        "gear_ratios": [0.35, 0.55, 0.75, 0.90, 1.00, 1.00],
        "require_neutral_to_arm": True,
    },
    "brake": {
        "deadzone": 0.05,
        "strength": 1.0,
    },
    "display": {"width": 960, "height": 720, "vsync": False},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Gabungkan config pengguna di atas default, rekursif per bagian.

    Artinya config.yaml boleh memuat sebagian kunci saja; sisanya memakai
    default, sehingga menambah opsi baru di versi berikutnya tidak merusak
    berkas config yang sudah ada.
    """
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_PATH
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return _deep_merge(DEFAULT_CONFIG, loaded)


def load_calibration(path: Path | None = None) -> dict:
    path = path or CALIBRATION_PATH
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_calibration(data: dict, path: Path | None = None) -> Path:
    path = path or CALIBRATION_PATH
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Dihasilkan oleh calibrate.py -- aman ditulis ulang.\n")
        handle.write("# Jalankan ulang calibrate.py kalau stir diganti atau\n")
        handle.write("# saklar mode pada PXN V9 digeser.\n\n")
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    return path


def save_trim(trim: float, path: Path | None = None) -> Path:
    """Simpan nilai trim ke config.yaml tanpa merusak komentar di dalamnya.

    Hanya baris `trim:` di dalam blok `steering:` yang disentuh; sisa berkas
    dibiarkan apa adanya. Salinan .bak dibuat sebelum menulis.
    """
    path = path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"{path} tidak ditemukan")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_steering = False
    written = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Kunci tingkat atas selalu mulai di kolom 0.
        if not line[0].isspace():
            in_steering = stripped.startswith("steering:")
            continue
        if in_steering and stripped.split(":")[0].strip() == "trim":
            indent = line[: len(line) - len(line.lstrip())]
            replacement = f"{indent}trim: {trim:.4f}"

            if "#" in line:
                # Pertahankan komentar DAN kolomnya, supaya blok steering tetap
                # rata setelah trim disimpan berkali-kali.
                column = line.index("#")
                comment = line[column:].rstrip("\n")
                padding = max(2, column - len(replacement))
                replacement += " " * padding + comment

            lines[index] = replacement + "\n"
            written = True
            break

    if not written:
        raise ValueError("kunci steering.trim tidak ditemukan di config.yaml")

    shutil.copyfile(path, path.with_suffix(".yaml.bak"))
    path.write_text("".join(lines), encoding="utf-8")
    return path
