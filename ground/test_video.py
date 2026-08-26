"""Deterministic latest-frame parser test; no network or camera required."""

from __future__ import annotations

import unittest

import socket
import threading

from rcground.video import CameraPing, MjpegStream


class _Response:
    def __init__(self, *chunks: bytes):
        self.chunks = list(chunks)

    def read1(self, _size: int) -> bytes:
        return self.chunks.pop(0)


class MjpegParserTests(unittest.TestCase):
    def test_one_read_publishes_only_latest_complete_jpeg(self):
        stream = MjpegStream("http://unused")
        response = _Response(b"noise\xff\xd8old\xff\xd9\xff\xd8new\xff\xd9", b"")
        stream._read_stream(response)
        jpeg, frame_id = stream.latest()
        self.assertEqual(jpeg, b"\xff\xd8new\xff\xd9")
        self.assertEqual(frame_id, 1)

    def test_decode_disabled_never_touches_pygame(self):
        """Default decode=False harus tetap murni parser, tanpa Surface."""
        stream = MjpegStream("http://unused")
        stream._read_stream(_Response(b"\xff\xd8junk\xff\xd9", b""))
        surface, frame_id = stream.latest_surface()
        self.assertIsNone(surface)
        self.assertEqual(frame_id, 1)

    def test_decode_enabled_publishes_surface_for_real_jpeg(self):
        """decode=True mendekode di thread stream, bukan di loop kendali."""
        import io

        import pygame

        pygame.init()
        buffer = io.BytesIO()
        pygame.image.save(pygame.Surface((8, 4)), buffer, "test.jpg")
        jpeg = buffer.getvalue()

        stream = MjpegStream("http://unused", decode=True)
        stream._read_stream(_Response(jpeg, b""))

        surface, frame_id = stream.latest_surface()
        self.assertEqual(frame_id, 1)
        self.assertIsNotNone(surface)
        self.assertEqual(surface.get_size(), (8, 4))
        pygame.quit()

    def test_corrupt_frame_with_decode_on_still_publishes_bytes(self):
        """Frame rusak tidak boleh menghentikan stream; byte tetap tersedia."""
        stream = MjpegStream("http://unused", decode=True)
        stream._read_stream(_Response(b"\xff\xd8bukan-jpeg\xff\xd9", b""))
        surface, _ = stream.latest_surface()
        jpeg, frame_id = stream.latest()
        self.assertIsNone(surface)
        self.assertEqual(jpeg, b"\xff\xd8bukan-jpeg\xff\xd9")
        self.assertEqual(frame_id, 1)


class StutterMetricTests(unittest.TestCase):
    """fps rata-rata menyembunyikan pembekuan; worst_gap_ms harus menangkapnya."""

    @staticmethod
    def _stream_with(intervals):
        import time as _t

        stream = MjpegStream("http://unused")
        t = _t.monotonic() - sum(intervals)
        for gap in intervals:
            stream._frame_times.append(t)
            t += gap
        return stream

    def test_smooth_stream_reports_small_gap(self):
        stream = self._stream_with([0.05] * 40)
        self.assertLess(stream.worst_gap_ms, 120)
        self.assertGreater(stream.fps, 15)

    def test_freeze_then_burst_is_caught_even_though_fps_looks_fine(self):
        """Pola nyata TCP tersendat: mulus, beku, lalu menyusul beruntun."""
        intervals = [0.05] * 30 + [0.40] + [0.005] * 5
        stream = self._stream_with(intervals)
        self.assertGreater(
            stream.worst_gap_ms, 350,
            "pembekuan 400 ms harus terlihat di worst_gap_ms",
        )
        self.assertGreater(
            stream.fps, 10,
            "fps sengaja tetap tampak wajar -- itulah kenapa metrik ini perlu",
        )

    def test_ongoing_freeze_shows_immediately(self):
        """Beku yang SEDANG berlangsung tidak boleh menunggu selesai dulu."""
        import time as _t

        stream = MjpegStream("http://unused")
        stream._frame_times.append(_t.monotonic() - 0.6)
        self.assertGreater(stream.worst_gap_ms, 500)

    def test_no_frames_reports_zero_not_a_crash(self):
        self.assertEqual(MjpegStream("http://unused").worst_gap_ms, 0.0)


class CameraPingTests(unittest.TestCase):
    """PING di HUD mengukur KAMERA, lewat TCP ke port HTTP-nya."""

    def test_host_and_port_parsed_from_stream_url(self):
        """URL stream, bukan host telanjang -- port default 80 kalau tak ditulis."""
        self.assertEqual(
            (CameraPing("http://192.168.8.61/stream").host,
             CameraPing("http://192.168.8.61/stream").port),
            ("192.168.8.61", 80),
        )
        probe = CameraPing("http://127.0.0.1:8080/stream")
        self.assertEqual((probe.host, probe.port), ("127.0.0.1", 8080))

    def test_interval_is_floored_to_protect_camera_sockets(self):
        """Firmware kamera hanya punya 3 socket -- probe tidak boleh menumpuk."""
        self.assertGreaterEqual(CameraPing("http://x/", interval=0.01).interval, 0.5)

    def test_measures_round_trip_against_a_real_listener(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        port = listener.getsockname()[1]

        accepted = threading.Event()

        def serve():
            try:
                conn, _ = listener.accept()
                conn.close()
                accepted.set()
            except OSError:
                pass

        threading.Thread(target=serve, daemon=True).start()
        try:
            rtt = CameraPing(f"http://127.0.0.1:{port}/stream")._probe()
            self.assertIsNotNone(rtt)
            self.assertGreaterEqual(rtt, 0.0)
            self.assertTrue(accepted.wait(2.0))
        finally:
            listener.close()

    def test_unreachable_camera_reports_none_not_a_stale_number(self):
        """Angka lama tidak boleh dipajang seolah kamera masih menjawab."""
        # Port 9 (discard) ditutup di loopback pada mesin biasa.
        probe = CameraPing("http://127.0.0.1:9/stream", timeout=0.3)
        self.assertIsNone(probe._probe())
        self.assertIsNone(probe.rtt_ms)


if __name__ == "__main__":
    unittest.main()
