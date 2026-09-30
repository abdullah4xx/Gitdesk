import argparse
import time

from .config import Config


def run_headless(cfg: Config) -> int:
    from .engine import Engine

    eng = Engine(cfg, on_state=lambda s, m: print(f"[{s}] {m}", flush=True))
    eng.start()
    if eng.state != "running":
        return 1
    try:
        while eng.state == "running":
            time.sleep(2)
            s = eng.stats
            if s and s.connected:
                print(f"  {s.fps:4.0f} fps  {s.kbps / 1000:5.1f} Mbps  rtt {s.rtt_ms:5.1f} ms  "
                      f"dropped {s.dropped}  [{s.encoder}]", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        eng.stop()
    return 0 if eng.state == "idle" else 1


def main() -> int:
    d = Config()
    ap = argparse.ArgumentParser("gitdesk", description="USB second monitor for Linux using an Android device")
    ap.add_argument("--headless", action="store_true", help="run without the GUI")
    ap.add_argument("--restore-display", action="store_true",
                    help="remove leftover GitDesk virtual outputs and re-assert the primary output, then exit")
    ap.add_argument("--port", type=int, default=d.port)
    ap.add_argument("--fps", type=int, default=d.fps)
    ap.add_argument("--bitrate", type=float, default=d.bitrate_kbps / 1000, help="Mbit/s (capped at 6)")
    ap.add_argument("--size", default=f"{d.width}x{d.height}", help="WxH or 'auto' (match device)")
    ap.add_argument("--encoder", default="auto", choices=["auto", "nvenc", "vah264", "vaapi", "x264"])
    ap.add_argument("--serial", default="", help="adb device serial")
    a = ap.parse_args()

    if a.restore_display:
        from .display import restore_display
        for line in restore_display() or ["nothing to clean up"]:
            print(line)
        return 0

    w = h = 0
    if a.size != "auto":
        w, h = map(int, a.size.lower().split("x"))
    cfg = Config(port=a.port, width=w, height=h, fps=a.fps, bitrate_kbps=int(a.bitrate * 1000),
                 encoder=a.encoder, adb_serial=a.serial)

    if a.headless:
        return run_headless(cfg)
    from .gui import run_gui
    return run_gui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
