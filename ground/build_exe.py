"""build_exe.py — bangun aplikasi darat RC Car menjadi .exe dengan PyInstaller.

Menghasilkan SATU folder `dist/RCCarField/` berisi:
    RCCar.exe          aplikasi utama (main.py)
    Kalibrasi.exe       wizard kalibrasi stir (calibrate.py)
    config.yaml         disalin dari sini, bisa diedit di sebelah exe
    calibration.yaml    disalin kalau sudah ada, kalau belum: dibuat kosong
                        (Kalibrasi.exe akan mengisinya saat pertama dijalankan)
    BACA-DULU.txt       ringkasan cara pakai di lapangan

Kedua exe dibangun dengan --onefile (satu file exe berdiri sendiri, tanpa
folder _internal terpisah) supaya menggabungkan RCCar.exe dan Kalibrasi.exe
ke dalam satu folder tidak perlu menyatukan dua folder _internal yang
berbeda-beda isinya.

SOAL PALING PENTING di build ini: exe yang dibundel PyInstaller menjalankan
kode dari folder ekstraksi sementara, BUKAN dari folder tempat exe itu
sendiri berada. Kalau ground/rcground/config.py masih memakai
Path(__file__) apa adanya untuk mencari config.yaml, config.yaml yang
pengguna edit di sebelah RCCar.exe TIDAK PERNAH terbaca -- exe akan diam-diam
memakai nilai default. Ini sudah diperbaiki di config.py (cek
getattr(sys, "frozen", False) dan pakai sys.executable), tapi kalau Anda
menambah skrip baru yang membaca berkas dengan Path(__file__), jebakan yang
sama akan muncul lagi di sana. Baca komentar di rcground/config.py sebelum
menambah pemuatan berkas baru.

Jalankan:
    python build_exe.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

GROUND_DIR = Path(__file__).resolve().parent
DIST_DIR = GROUND_DIR / "dist"
OUTPUT_DIR = DIST_DIR / "RCCarField"
BUILD_DIR = GROUND_DIR / "build_pyinstaller"
SPEC_DIR = BUILD_DIR / "specs"

BACA_DULU = """RC CAR -- APLIKASI DARAT (GROUND STATION)
===========================================

ISI FOLDER INI
  RCCar.exe          aplikasi utama -- jalankan ini saat mau mengemudi
  Kalibrasi.exe       wizard kalibrasi stir PXN V9 -- jalankan ini dulu
                      sebelum RCCar.exe kalau stir baru dipasang atau
                      saklar mode PXN digeser
                      Jalankan `Kalibrasi.exe --servo` untuk menyesuaikan
                      titik servo kiri/tengah/kanan tanpa arm mobil.
  Latensi.exe         ukur latensi video sesungguhnya (glass-to-glass).
                      Arahkan kamera mobil ke layar kiri, tekan SPASI untuk
                      membekukan, selisih dua angka itulah latensinya.
  config.yaml         semua setelan (jaringan, kurva gas, batas kecepatan,
                      trim, dll). Edit dengan Notepad biasa, lalu jalankan
                      ulang RCCar.exe -- TIDAK perlu build ulang exe-nya.
  calibration.yaml    hasil Kalibrasi.exe. Jangan diedit manual.

SEBELUM PERTAMA KALI DIPAKAI (per LattePanda / per mobil)
  1. Buka config.yaml dengan Notepad.
  2. Cari baris "unit:" di paling atas, isi 1, 2, atau 3 sesuai mobil yang
     dikendalikan LattePanda ini. HARUS sama dengan UNIT_ID yang di-flash
     ke ESP32 mobil dan kamera itu.
  3. Simpan config.yaml.
  4. Colok stir PXN V9, jalankan Kalibrasi.exe, ikuti wizard-nya sampai
     selesai.
  5. Jalankan RCCar.exe.

URUTAN MENYALAKAN DI LAPANGAN
  1. Nyalakan hotspot WiFi (router GL.iNet) LEBIH DULU.
  2. Sambungkan baterai mobil, tunggu LED ESP32 dari kedip cepat jadi
     kedip lambat (artinya WiFi sudah tersambung).
  3. Jalankan RCCar.exe.
  4. Perhatikan pojok kiri atas layar: harus tertulis "UNIT <nomor>" yang
     SESUAI dengan mobil di depan Anda. Kalau nomornya salah, tutup
     RCCar.exe, perbaiki "unit:" di config.yaml, jalankan ulang.
  5. Tunggu sampai muncul "Mobil ditemukan" di pojok kiri atas, baru tekan
     SPASI untuk ARM.

TOMBOL
  SPASI   arm / disarm
  E       stop darurat
  [ ]     geser trim stir
  H       klakson (tahan)
  G / Shift+G   ganti pack suara gas
  N / Shift+N   ganti pack suara klakson
  M / Shift+M   ganti pack suara arm
  F5      simpan trim ke config.yaml
  F11     layar penuh
  ESC     keluar

KALAU ADA MASALAH
  - Layar HUD menunjukkan "UNIT" yang salah -> config.yaml, ganti "unit:".
  - Mobil tidak ditemukan -> pastikan hotspot menyala, mobil dan LattePanda
    di jaringan yang sama, dan IP di config.yaml (atau turunan dari "unit:")
    sesuai dengan mobil yang di-flash.
  - Stir tidak terdeteksi -> aplikasi otomatis memakai keyboard (panah).
    Jalankan Kalibrasi.exe setelah mencolok stir yang benar.
  - Baca docs/balapan-3-unit.md dan README.md di folder proyek untuk
    penjelasan lebih lengkap (kedua berkas itu ada di repo sumber, bukan
    di folder exe ini).
"""


def _clean(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def build_one(script: str, name: str, extra_args: list[str] | None = None) -> None:
    print(f"\n=== membangun {name}.exe dari {script} ===")
    PyInstaller.__main__.run(
        [
            str(GROUND_DIR / script),
            "--name",
            name,
            "--onefile",
            # Konsol dibiarkan tampil (bukan --noconsole): pesan error dan
            # print() diagnostik (mis. "Gagal memulai: ...", RTT, status
            # stir) harus tetap terlihat di lapangan. Menyembunyikannya
            # hanya membuat masalah lebih susah dilacak tanpa laptop lain.
            "--console",
            "--distpath",
            str(OUTPUT_DIR),
            "--workpath",
            str(BUILD_DIR / name),
            "--specpath",
            str(SPEC_DIR),
            "--noconfirm",
            "--clean",
            *(extra_args or []),
        ]
    )


def main() -> int:
    _clean(DIST_DIR)
    _clean(BUILD_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --add-data membundel assets/sfx/ (manifest.yaml + mp3) DI DALAM
    # RCCar.exe, berbeda dari config.yaml/calibration.yaml yang disalin ke
    # SEBELAH exe di bawah -- lihat catatan panjang di rcground/sfx.py
    # (_sfx_root) soal kenapa assets/sfx tidak perlu bisa diedit pengguna
    # sehingga aman dibundel ke dalam, dan soal sys._MEIPASS sebagai lokasi
    # ekstraksinya saat exe --onefile berjalan. PENTING: pemisah sumber;tujuan
    # pada --add-data PyInstaller di Windows memakai TITIK KOMA (;), bukan
    # titik dua (:) seperti di Linux/Mac -- kalau build ini pernah dipindah
    # ke CI Linux/Mac, baris ini harus disesuaikan (os.pathsep).
    sfx_add_data = f"{GROUND_DIR / 'assets' / 'sfx'};assets/sfx"
    build_one("main.py", "RCCar", extra_args=["--add-data", sfx_add_data])
    # Kalibrasi.exe tidak memutar suara apa pun, jadi tidak perlu membundel
    # assets/sfx -- menghematnya membuat exe ini tetap kecil.
    build_one("calibrate.py", "Kalibrasi")
    # Latensi.exe ikut dibangun karena pengukuran latensi justru paling perlu
    # dilakukan DI LAPANGAN, di LattePanda, dengan mobil dan WiFi yang
    # sesungguhnya -- dan di sana belum tentu ada Python terpasang. Tanpa exe
    # ini, satu-satunya cara mengukur adalah membawa laptop pengembangan ke
    # lapangan. Sama seperti Kalibrasi.exe, tidak perlu assets/sfx.
    build_one("latency_test.py", "Latensi")

    # config.yaml dan calibration.yaml DI LUAR exe, di sebelahnya, supaya
    # bisa diedit langsung dan langsung terbaca -- lihat catatan panjang di
    # rcground/config.py soal kenapa ini tidak otomatis benar begitu saja
    # di dalam bundel PyInstaller.
    src_config = GROUND_DIR / "config.yaml"
    dst_config = OUTPUT_DIR / "config.yaml"
    shutil.copyfile(src_config, dst_config)
    print(f"disalin: {src_config} -> {dst_config}")

    src_calib = GROUND_DIR / "calibration.yaml"
    dst_calib = OUTPUT_DIR / "calibration.yaml"
    if src_calib.exists():
        shutil.copyfile(src_calib, dst_calib)
        print(f"disalin: {src_calib} -> {dst_calib}")
    else:
        dst_calib.write_text(
            "# Belum ada kalibrasi -- jalankan Kalibrasi.exe dulu.\n",
            encoding="utf-8",
        )
        print(f"dibuat kosong: {dst_calib} (jalankan Kalibrasi.exe untuk mengisinya)")

    (OUTPUT_DIR / "BACA-DULU.txt").write_text(BACA_DULU, encoding="utf-8")
    print(f"ditulis: {OUTPUT_DIR / 'BACA-DULU.txt'}")

    print(f"\nSELESAI. Folder siap pakai: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
