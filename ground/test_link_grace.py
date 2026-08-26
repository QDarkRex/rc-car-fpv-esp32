"""Kedipan tautan sesaat tidak boleh mengubah tampilan maupun suara.

Regresi nyata yang ditangkap di sini: telemetri 10 Hz + link_timeout_ms 500
membuat link.connected jatuh hanya karena 5 paket berturut hilang. Di 2,4 GHz
yang padat itu terjadi terus-menerus, dan dulu SATU kedipan sesaat mengubah
tiga hal sekaligus -- banner jadi FAILSAFE, HUD menampilkan DISARMED walau
mobil masih armed, dan sfx.update(active=False) mematikan mesin sehingga
panggilan berikutnya memutar suara starter DARI AWAL.

Yang diuji di sini murni aturan tenggangnya, tanpa jaringan dan tanpa audio.
"""

from __future__ import annotations

import unittest


class _Grace:
    """Cerminan persis aturan tenggang di GroundStation.run()."""

    def __init__(self, grace: float):
        self.grace = grace
        self._lost_since: float | None = None

    def step(self, now: float, connected: bool) -> bool:
        if connected:
            self._lost_since = None
        elif self._lost_since is None:
            self._lost_since = now
        return (
            self._lost_since is not None
            and (now - self._lost_since) >= self.grace
        )


class LinkGraceTests(unittest.TestCase):
    def test_short_blip_never_reports_lost(self):
        """RTO sepersekian detik -- persis yang terukur lewat ping."""
        g = _Grace(2.5)
        self.assertFalse(g.step(0.0, True))
        for t in (0.02, 0.2, 0.5, 0.9):          # putus ~0,9 detik
            self.assertFalse(g.step(t, False), f"berkedut di t={t}")
        self.assertFalse(g.step(1.0, True))       # pulih

    def test_sustained_outage_still_reports_lost(self):
        """Tenggang menyerap kedipan, bukan menyembunyikan putus sungguhan.

        Tenggang dihitung dari SAAT PUTUS DIMULAI, bukan dari nol. Putus
        mulai t=1.0 dengan tenggang 2.5 berarti ambangnya t=3.5.
        """
        g = _Grace(2.5)
        g.step(0.0, True)
        self.assertFalse(g.step(1.0, False))   # putus mulai di sini
        self.assertFalse(g.step(3.4, False))   # 2,4 detik berjalan -- belum
        self.assertTrue(g.step(3.5, False))    # tepat 2,5 detik -- lost
        self.assertTrue(g.step(9.0, False))

    def test_recovery_resets_the_timer(self):
        """Putus 2 detik, pulih sebentar, putus 2 detik lagi = tetap tidak lost."""
        g = _Grace(2.5)
        self.assertFalse(g.step(0.0, False))
        self.assertFalse(g.step(2.0, False))
        self.assertFalse(g.step(2.1, True))       # pulih -> timer nol lagi
        self.assertFalse(g.step(4.0, False))
        self.assertFalse(g.step(4.5, False))

    def test_default_grace_absorbs_a_full_second_of_loss(self):
        """Nilai bawaan harus cukup untuk RTO yang benar-benar dilaporkan."""
        from rcground import config as cfg

        grace = cfg.DEFAULT_CONFIG["network"]["link_grace_ms"] / 1000.0
        timeout = cfg.DEFAULT_CONFIG["network"]["link_timeout_ms"] / 1000.0
        self.assertGreaterEqual(grace, 1.0, "harus menyerap putus 1 detik penuh")
        self.assertGreater(
            grace, timeout,
            "tenggang harus lebih longgar daripada deteksi mentahnya",
        )

    def test_thirty_second_grace_survives_a_long_rough_patch(self):
        """Setelan sekarang: putus-nyambung 25 detik tidak boleh memicu apa pun.

        Meniru WiFi buruk yang sebenarnya -- bukan satu putus mulus, tapi
        rentetan putus pendek dengan pemulihan sekejap di antaranya. Setiap
        pemulihan menolkan pewaktu, jadi tidak satu pun mencapai ambang.
        """
        g = _Grace(30.0)
        t = 0.0
        while t < 25.0:
            self.assertFalse(g.step(t, False), f"berkedut di t={t:.1f}")
            t += 0.8
            self.assertFalse(g.step(t, True), f"berkedut di t={t:.1f}")
            t += 0.2

    def test_truly_dead_link_still_reported_after_thirty_seconds(self):
        """Tenggang 30 detik tetap melaporkan, bukan menyembunyikan selamanya."""
        g = _Grace(30.0)
        g.step(0.0, True)
        self.assertFalse(g.step(1.0, False))
        self.assertFalse(g.step(30.9, False))
        self.assertTrue(g.step(31.0, False))


if __name__ == "__main__":
    unittest.main()
