"""Deterministic latest-frame parser test; no network or camera required."""

from __future__ import annotations

import unittest

from rcground.video import MjpegStream


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


if __name__ == "__main__":
    unittest.main()
