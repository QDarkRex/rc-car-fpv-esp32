"""Perakitan ulang video UDP: fragmen hilang membuang SATU frame, bukan aliran.

Inti perbedaannya dengan HTTP/TCP diuji di sini. Pada TCP, satu segmen
hilang menahan seluruh aliran sampai kiriman ulangnya sampai. Pada UDP,
fragmen hilang berarti satu frame tidak lengkap lalu dibuang, dan frame
BERIKUTNYA tetap sampai tepat waktu -- itulah yang harus dibuktikan.
"""

from __future__ import annotations

import unittest

from rcground import protocol as proto
from rcground.video import UdpVideoStream

UNIT = 2


def _stream():
    """UdpVideoStream tanpa socket dan tanpa thread -- murni logika perakitan."""
    stream = UdpVideoStream.__new__(UdpVideoStream)
    stream.unit_id = UNIT
    stream._decode = False
    import collections
    import threading

    stream._lock = threading.Lock()
    stream._frame = None
    stream._surface = None
    stream._frame_id = 0
    stream._frame_times = collections.deque(maxlen=60)
    stream._pending = {}
    stream._newest_done = -1
    stream.connected = False
    stream.error = None
    stream.dropped_frames = 0
    return stream


def _fragments(frame_id: int, jpeg: bytes, unit: int = UNIT):
    size = proto.VIDEO_PAYLOAD_MAX
    chunks = [jpeg[i:i + size] for i in range(0, len(jpeg), size)] or [b""]
    return [
        proto.parse_video(proto.pack_video(unit, frame_id, i, len(chunks), c))
        for i, c in enumerate(chunks)
    ]


class ProtocolTests(unittest.TestCase):
    def test_roundtrip_preserves_payload(self):
        payload = bytes(range(256)) * 5
        frag = proto.parse_video(proto.pack_video(2, 1234, 3, 9, payload))
        self.assertEqual(
            (frag.unit_id, frag.frame_id, frag.index, frag.count, frag.payload),
            (2, 1234, 3, 9, payload),
        )

    def test_header_is_ten_bytes_so_payload_fits_one_datagram(self):
        packet = proto.pack_video(1, 0, 0, 1, b"x" * proto.VIDEO_PAYLOAD_MAX)
        self.assertEqual(len(packet), 10 + proto.VIDEO_PAYLOAD_MAX)
        self.assertLess(len(packet), 1472, "harus muat satu datagram tanpa fragmentasi IP")

    def test_oversized_payload_is_refused_at_pack_time(self):
        with self.assertRaises(ValueError):
            proto.pack_video(1, 0, 0, 1, b"x" * (proto.VIDEO_PAYLOAD_MAX + 1))

    def test_malformed_packets_are_rejected(self):
        good = proto.pack_video(1, 0, 0, 1, b"halo")
        self.assertIsNone(proto.parse_video(b""))
        self.assertIsNone(proto.parse_video(good[:6]))
        self.assertIsNone(proto.parse_video(b"XX" + good[2:]))          # magic salah
        self.assertIsNone(proto.parse_video(good[:2] + b"\x99" + good[3:]))  # versi salah
        self.assertIsNone(proto.parse_video(good + b"kelebihan"))       # panjang tidak cocok
        self.assertIsNone(proto.parse_video(proto.pack_video(1, 0, 0, 0, b"x")))  # count 0
        self.assertIsNone(proto.parse_video(proto.pack_video(1, 0, 5, 2, b"x")))  # index >= count

    def test_subscribe_roundtrip(self):
        self.assertEqual(proto.parse_subscribe(proto.pack_subscribe(3)), 3)
        self.assertIsNone(proto.parse_subscribe(b"XX\x03\x01"))
        self.assertIsNone(proto.parse_subscribe(b"RS\x03"))


class ReassemblyTests(unittest.TestCase):
    def test_complete_frame_is_published(self):
        stream = _stream()
        jpeg = b"\xff\xd8" + b"A" * 3000 + b"\xff\xd9"
        for frag in _fragments(1, jpeg):
            stream._accept(frag)
        self.assertEqual(stream.latest(), (jpeg, 1))
        self.assertTrue(stream.connected)

    def test_fragments_out_of_order_still_reassemble(self):
        """UDP tidak menjamin urutan -- perakitan tidak boleh mengandalkannya."""
        stream = _stream()
        jpeg = b"\xff\xd8" + b"B" * 4000 + b"\xff\xd9"
        frags = _fragments(7, jpeg)
        for frag in reversed(frags):
            stream._accept(frag)
        self.assertEqual(stream.latest()[0], jpeg)

    def test_lost_fragment_drops_only_that_frame(self):
        """INTI: frame berikutnya tetap sampai, aliran tidak membeku."""
        stream = _stream()
        rusak = b"\xff\xd8" + b"C" * 4000 + b"\xff\xd9"
        utuh = b"\xff\xd8" + b"D" * 4000 + b"\xff\xd9"

        for frag in _fragments(10, rusak)[:-1]:   # satu fragmen hilang
            stream._accept(frag)
        self.assertIsNone(stream.latest()[0], "frame tidak lengkap tidak boleh terbit")

        for frag in _fragments(11, utuh):
            stream._accept(frag)
        self.assertEqual(stream.latest()[0], utuh, "frame berikutnya harus tetap sampai")
        self.assertEqual(stream.dropped_frames, 1)

    def test_stale_fragments_after_a_newer_frame_are_ignored(self):
        stream = _stream()
        baru = b"\xff\xd8" + b"E" * 2000 + b"\xff\xd9"
        for frag in _fragments(20, baru):
            stream._accept(frag)
        published = stream.latest()

        for frag in _fragments(19, b"\xff\xd8" + b"F" * 2000 + b"\xff\xd9"):
            stream._accept(frag)
        self.assertEqual(stream.latest(), published, "frame lama tidak boleh menggantikan")

    def test_frame_id_wraparound_is_not_mistaken_for_old(self):
        """Pembungkusan di 65535 tidak boleh membuat frame baru tampak usang."""
        stream = _stream()
        for frag in _fragments(65534, b"\xff\xd8" + b"G" * 100 + b"\xff\xd9"):
            stream._accept(frag)
        sesudah = b"\xff\xd8" + b"H" * 100 + b"\xff\xd9"
        for frag in _fragments(1, sesudah):     # sudah membungkus
            stream._accept(frag)
        self.assertEqual(stream.latest()[0], sesudah)

    def test_other_unit_never_contributes_a_frame(self):
        """Kamera unit lain tidak boleh ikut membentuk gambar di sini."""
        stream = _stream()
        for frag in _fragments(1, b"\xff\xd8" + b"X" * 2000 + b"\xff\xd9", unit=3):
            if frag.unit_id == stream.unit_id:
                stream._accept(frag)
        self.assertIsNone(stream.latest()[0])

    def test_incomplete_frames_do_not_pile_up(self):
        stream = _stream()
        for fid in range(40):
            for frag in _fragments(fid, b"\xff\xd8" + b"Z" * 4000 + b"\xff\xd9")[:-1]:
                stream._accept(frag)
        self.assertLessEqual(len(stream._pending), 8, "harus dibatasi keras")


if __name__ == "__main__":
    unittest.main()
