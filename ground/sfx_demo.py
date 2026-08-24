"""Standalone SFX tester; no wheel, network, camera, or RC car required.

Run with ``python sfx_demo.py --silent`` on a machine without an audio device.
Keys: SPACE arm/disarm, UP/DOWN throttle, H hold horn, E estop,
G/SHIFT+G gas pack, N/SHIFT+N horn pack, M/SHIFT+M ignition pack, ESC quit.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

if "--silent" in sys.argv:
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import pygame
except ImportError:
    print("sfx_demo membutuhkan pygame. Pasang dependensi ground terlebih dahulu.")
    raise SystemExit(2)

from rcground.sfx import SfxEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Tester SFX RC Car tanpa hardware")
    parser.add_argument("--silent", action="store_true", help="gunakan SDL audio dummy")
    parser.add_argument("--seconds", type=float, default=0.0, help="berhenti otomatis setelah N detik")
    args = parser.parse_args()

    pygame.init()
    pygame.display.set_mode((640, 240))
    pygame.display.set_caption("RC Car SFX Demo")
    font = pygame.font.Font(None, 28)
    engine = SfxEngine(enabled=True)
    armed = False
    throttle = 0.0
    started = time.monotonic()
    last = started
    last_print = 0.0
    running = True

    while running:
        now = time.monotonic()
        dt = min(0.1, now - last)
        last = now
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    armed = not armed
                    if armed:
                        engine.start_engine()
                    else:
                        engine.stop_engine()
                elif event.key == pygame.K_e:
                    armed = False
                    throttle = 0.0
                    engine.stop_engine(fast=True)
                elif event.key == pygame.K_UP:
                    throttle = min(1.0, throttle + 0.1)
                elif event.key == pygame.K_DOWN:
                    throttle = max(0.0, throttle - 0.1)
                elif event.key == pygame.K_g:
                    engine.prev_pack("gas") if event.mod & pygame.KMOD_SHIFT else engine.next_pack("gas")
                elif event.key == pygame.K_n:
                    engine.prev_pack("horn") if event.mod & pygame.KMOD_SHIFT else engine.next_pack("horn")
                elif event.key == pygame.K_m:
                    engine.prev_pack("arm") if event.mod & pygame.KMOD_SHIFT else engine.next_pack("arm")

        keys = pygame.key.get_pressed()
        engine.update_horn(bool(keys[pygame.K_h]))
        engine.update(dt, throttle, armed)
        if now - last_print >= 0.25:
            last_print = now
            print(
                f"state={engine.state:13s} rpm={engine.virtual_rpm:.2f} "
                f"throttle={throttle:.1f} horn={'on' if engine.horn_active else 'off'}"
            )

        screen = pygame.display.get_surface()
        screen.fill((15, 17, 22))
        lines = (
            "SPACE arm/disarm | UP/DOWN throttle | hold H horn | E estop",
            "G/N/M select packs (SHIFT = previous) | ESC quit",
            f"{engine.state}   RPM {engine.virtual_rpm:.2f}   GAS {throttle:.1f}",
        )
        for row, line in enumerate(lines):
            screen.blit(font.render(line, True, (225, 230, 238)), (20, 35 + row * 42))
        pygame.display.flip()
        if args.seconds > 0 and now - started >= args.seconds:
            running = False
        time.sleep(0.01)

    engine.update_horn(False)
    engine.stop_engine(fast=True)
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
