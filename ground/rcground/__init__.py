"""Ground station RC Car — paket internal.

Modul:
    protocol -- struktur paket UDP (kembar dengan protocol.h di firmware)
    link     -- transport UDP, discovery, RTT, watchdog tautan
    wheel    -- pembacaan stir PXN dan seluruh kurva/limit kendali
    video    -- pembaca stream MJPEG dari ESP32-CAM
    hud      -- overlay HUD di atas video
    config   -- pemuatan config.yaml dan calibration.yaml
"""

__version__ = "1.0.0"
