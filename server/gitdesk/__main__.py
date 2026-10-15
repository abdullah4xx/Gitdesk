import argparse
import threading
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


def run_mirror(serial: str, bitrate_mbps: int, view_only: bool) -> int:
    """Show the Android screen on this PC (scrcpy) and block until the window is closed."""
    from .mirror import Mirror, MirrorError

    done, result = threading.Event(), []

    def on_exit(msg: str) -> None:
        result.append(msg)
        done.set()

    m = Mirror(serial=serial, bitrate_mbps=bitrate_mbps, control=not view_only, on_exit=on_exit)
    try:
        m.start()
    except MirrorError as e:
        print(e)
        return 1
    try:
        done.wait()
    except KeyboardInterrupt:
        m.stop()
        done.wait(3)
    print(result[0] if result else "Mirroring stopped")
    return 0


def main() -> int:
    d = Config()
    ap = argparse.ArgumentParser("gitdesk", description="USB second monitor for Linux using an Android device")
    ap.add_argument("--headless", action="store_true", help="run without the GUI")
    ap.add_argument("--restore-display", action="store_true",
                    help="remove leftover GitDesk virtual outputs and re-assert the primary output, then exit")
    ap.add_argument("--mirror", action="store_true",
                    help="show the Android screen on this PC (needs scrcpy), then exit when the window closes")
    ap.add_argument("--mirror-bitrate", type=int, default=8, help="mirror video bitrate in Mbit/s (default 8)")
    ap.add_argument("--mirror-view-only", action="store_true",
                    help="mirror without forwarding mouse/keyboard to the phone")
    ap.add_argument("--port", type=int, default=d.port)
    ap.add_argument("--fps", type=int, default=d.fps)
    ap.add_argument("--bitrate", type=float, default=d.bitrate_kbps / 1000,
                    help=f"Mbit/s (capped at {d.max_bitrate_kbps // 1000})")
    ap.add_argument("--size", default=f"{d.width}x{d.height}", help="WxH or 'auto' (match device)")
    ap.add_argument("--encoder", default="auto", choices=["auto", "nvenc", "vah264", "vaapi", "x264"])
    ap.add_argument("--serial", default="", help="adb device serial")
    a = ap.parse_args()

    if a.restore_display:
        from .display import restore_display
        for line in restore_display() or ["nothing to clean up"]:
            print(line)
        return 0

    if a.mirror:
        return run_mirror(a.serial, max(1, a.mirror_bitrate), a.mirror_view_only)

    w = h = 0
    if a.size != "auto":
        w, h = map(int, a.size.lower().split("x"))
    kbps = int(a.bitrate * 1000)
    kbps = max(d.min_bitrate_kbps, min(kbps, d.max_bitrate_kbps))   # the cap was documented but never enforced
    cfg = Config(port=a.port, width=w, height=h, fps=a.fps, bitrate_kbps=kbps,
                 encoder=a.encoder, adb_serial=a.serial)

    if a.headless:
        return run_headless(cfg)
    from .gui import run_gui
    return run_gui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
