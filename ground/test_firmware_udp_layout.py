"""Header video UDP di firmware harus KEMBAR dengan protocol.py.

Keduanya menulis/membaca byte yang sama persis, tapi di bahasa berbeda dan
di berkas berbeda -- jenis pasangan yang paling mudah menyimpang diam-diam.
Kalau menyimpang, gejalanya bukan error melainkan video yang tidak pernah
muncul, atau gambar sampah, tanpa petunjuk di mana salahnya.

Test ini membaca SUMBER firmware apa adanya, jadi ia ikut gagal kalau
seseorang mengubah salah satu sisi tanpa mengubah yang lain.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from rcground import protocol as proto

FIRMWARE = (
    Path(__file__).resolve().parent.parent
    / "firmware" / "rc_cam_esp32_udp" / "rc_cam_esp32_udp.ino"
)


class FirmwareUdpLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FIRMWARE.exists():
            raise unittest.SkipTest(f"{FIRMWARE} tidak ada")
        cls.src = FIRMWARE.read_text(encoding="utf-8", errors="replace")

    def _define(self, name: str) -> int:
        match = re.search(rf"^#define\s+{name}\s+(\d+)", self.src, re.M)
        self.assertIsNotNone(match, f"#define {name} tidak ditemukan di firmware")
        return int(match.group(1))

    def test_constants_match(self):
        self.assertEqual(self._define("VIDEO_PORT"), proto.VIDEO_PORT)
        self.assertEqual(self._define("PROTOCOL_VERSION"), proto.PROTOCOL_VERSION)
        self.assertEqual(self._define("VIDEO_PAYLOAD_MAX"), proto.VIDEO_PAYLOAD_MAX)
        self.assertEqual(self._define("VIDEO_HEADER_SIZE"), proto.VIDEO_HEADER_SIZE)

    def test_header_byte_layout_matches_struct_format(self):
        """Tiap header[i] di firmware harus menempati offset yang sama di Python."""
        assignments = dict(
            (int(i), expr.strip())
            for i, expr in re.findall(r"header\[(\d+)\]\s*=\s*([^;]+);", self.src)
        )
        # Semua sepuluh offset harus ditulis; satu saja terlewat berarti byte
        # sampah terkirim di posisi itu.
        self.assertEqual(
            sorted(assignments), list(range(proto.VIDEO_HEADER_SIZE)),
            "setiap byte header harus diisi eksplisit",
        )

        self.assertIn("'R'", assignments[0])
        self.assertIn("'V'", assignments[1])
        self.assertIn("PROTOCOL_VERSION", assignments[2])
        self.assertIn("UNIT_ID", assignments[3])
        # frame_id u16 little-endian di offset 4..5
        self.assertIn("frameId", assignments[4])
        self.assertNotIn(">>", assignments[4], "offset 4 harus byte RENDAH")
        self.assertIn("frameId >> 8", assignments[5].replace("  ", " "))
        # index lalu count -- urutan ini mudah tertukar
        self.assertIn("index", assignments[6])
        self.assertIn("count", assignments[7])
        # payload_len u16 little-endian di offset 8..9
        self.assertIn("chunk", assignments[8])
        self.assertNotIn(">>", assignments[8], "offset 8 harus byte RENDAH")
        self.assertIn("chunk >> 8", assignments[9].replace("  ", " "))

    def test_subscribe_check_matches_python(self):
        """Firmware harus menolak paket subscribe yang bukan miliknya."""
        self.assertIn("'R'", self.src)
        self.assertIn("'S'", self.src)
        self.assertRegex(
            self.src, r"buffer\[2\]\s*!=\s*PROTOCOL_VERSION",
            "firmware harus memeriksa versi paket subscribe",
        )
        self.assertRegex(
            self.src, r"buffer\[3\]\s*!=\s*UNIT_ID",
            "firmware harus menolak subscribe untuk unit lain",
        )

    def test_camera_stops_sending_without_a_subscriber(self):
        """Tanpa backpressure TCP, kamera yang ditinggalkan harus berhenti sendiri."""
        self.assertIn("SUBSCRIBE_TIMEOUT_MS", self.src)
        self.assertIn("hasSubscriber()", self.src)

    def test_python_parser_accepts_a_firmware_shaped_packet(self):
        """Bentuk paket yang dibangun firmware harus lolos parser Python.

        Header dirakit di sini persis seperti sendFrame() merakitnya, lalu
        diuji dengan parser sungguhan -- menutup celah kalau salah satu sisi
        diam-diam berganti endianness atau menukar index/count.
        """
        frame_id, index, count, payload = 0x1234, 2, 7, b"payload"
        header = bytes([
            ord("R"), ord("V"), proto.PROTOCOL_VERSION, 3,
            frame_id & 0xFF, (frame_id >> 8) & 0xFF,
            index, count,
            len(payload) & 0xFF, (len(payload) >> 8) & 0xFF,
        ])
        fragment = proto.parse_video(header + payload)
        self.assertIsNotNone(fragment, "parser Python menolak paket bentukan firmware")
        self.assertEqual(
            (fragment.unit_id, fragment.frame_id, fragment.index,
             fragment.count, fragment.payload),
            (3, frame_id, index, count, payload),
        )


if __name__ == "__main__":
    unittest.main()
