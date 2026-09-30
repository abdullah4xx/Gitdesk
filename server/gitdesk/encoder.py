"""Capture -> low-latency H.264/AVC (Annex-B access units) via GStreamer, with encoder auto-fallback.

Only H.264 is ever produced (Main profile by default): HEVC is never negotiated, which avoids the
hardware-decoder limitations of mid-range tablets such as the Galaxy Tab A7.
"""
import threading

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo  # noqa: E402

Gst.init(None)


class EncoderError(RuntimeError):
    pass


# key -> (element, launch fragment). Encoder is always named "enc" so bitrate can be changed live.
ENC = {
    "nvenc": ("nvh264enc",
              "nvh264enc name=enc preset=low-latency-hq zerolatency=true rc-mode=cbr bitrate={kbps} gop-size={gop}"),
    "vah264": ("vah264enc",
               "vah264enc name=enc rate-control=cbr bitrate={kbps} key-int-max={gop} b-frames=0 target-usage=7"),
    "vaapi": ("vaapih264enc",
              "vaapih264enc name=enc rate-control=cbr bitrate={kbps} keyframe-period={gop} max-bframes=0"),
    "x264": ("x264enc",
             "x264enc name=enc tune=zerolatency speed-preset=ultrafast bitrate={kbps} key-int-max={gop} "
             "bframes=0 sliced-threads=true"),
}
ORDER = ["nvenc", "vah264", "vaapi", "x264"]


def available_encoders() -> list[str]:
    return [k for k in ORDER if Gst.ElementFactory.find(ENC[k][0])]


class Streamer:
    """on_au(data: bytes, keyframe: bool, pts_us: int) is called from a GStreamer thread."""

    def __init__(self, cfg, target, on_au, on_error):
        self.cfg, self.target, self.on_au, self.on_error = cfg, target, on_au, on_error
        self.pipe = self.sink = None
        self._run = False

    def _candidates(self) -> list[str]:
        pool = ORDER if self.cfg.encoder == "auto" else [self.cfg.encoder]
        keys = [k for k in pool if k in ENC and Gst.ElementFactory.find(ENC[k][0])]
        if not keys:
            raise EncoderError("H.264 encoder unavailable — sudo apt install gstreamer1.0-plugins-ugly "
                               "gstreamer1.0-plugins-bad gstreamer1.0-vaapi")
        return keys

    def _desc(self, key: str) -> str:
        c, t = self.cfg, self.target
        # 1 s GOP: a lost/dropped frame is repaired within a second even without an explicit IDR request
        enc = ENC[key][1].format(kbps=c.bitrate_kbps, gop=c.fps)
        return (f"{t.source} "
                "! queue leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=0 "
                "! videoconvert n-threads=4 ! videoscale "
                f"! video/x-raw,format=NV12,width={t.width},height={t.height} "
                f"! {enc} "
                f"! video/x-h264,profile={c.h264_profile} "
                "! h264parse config-interval=-1 "
                "! video/x-h264,stream-format=byte-stream,alignment=au "
                "! appsink name=sink emit-signals=true sync=false max-buffers=4 drop=false")

    def start(self) -> str:
        last = ""
        for key in self._candidates():
            try:
                pipe = Gst.parse_launch(self._desc(key))
            except GLib.Error as e:
                last = f"{key}: {e.message}"
                continue
            sink = pipe.get_by_name("sink")
            sink.connect("new-sample", self._on_sample)   # connect before PLAYING: never miss the first IDR
            pipe.set_state(Gst.State.PLAYING)
            ret, _, _ = pipe.get_state(3 * Gst.SECOND)
            msg = pipe.get_bus().timed_pop_filtered(300 * Gst.MSECOND, Gst.MessageType.ERROR)
            if ret == Gst.StateChangeReturn.FAILURE or msg:
                last = f"{key}: {msg.parse_error()[0].message if msg else 'state change failed'}"
                pipe.set_state(Gst.State.NULL)
                continue
            self.pipe, self.sink, self._run = pipe, sink, True
            threading.Thread(target=self._watch, args=(pipe,), daemon=True, name="gst-bus").start()
            return ENC[key][0]
        raise EncoderError(last or "no encoder could be started")

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                data = bytes(info.data)
            finally:
                buf.unmap(info)
            from .protocol import now_us
            self.on_au(data, not buf.has_flags(Gst.BufferFlags.DELTA_UNIT), now_us())
        return Gst.FlowReturn.OK

    def _watch(self, pipe) -> None:
        bus = pipe.get_bus()
        while self._run:
            m = bus.timed_pop_filtered(250 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if m:
                if self._run:
                    self.on_error(m.parse_error()[0].message if m.type == Gst.MessageType.ERROR
                                  else "capture stream ended")
                return

    def request_keyframe(self) -> None:
        sink = self.sink
        if sink is not None:
            sink.send_event(GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0))

    def set_bitrate(self, kbps: int) -> int:
        """Change the encoder bitrate live. Returns the applied value (clamped), or 0 on failure."""
        kbps = max(self.cfg.min_bitrate_kbps, min(int(kbps), self.cfg.max_bitrate_kbps))
        pipe = self.pipe
        enc = pipe.get_by_name("enc") if pipe is not None else None
        if enc is None:
            return 0
        try:
            enc.set_property("bitrate", kbps)
        except Exception:  # noqa: BLE001 — property not mutable on this encoder build
            return 0
        return kbps

    def stop(self) -> None:
        self._run = False
        pipe, self.pipe, self.sink = self.pipe, None, None
        if pipe is not None:
            pipe.set_state(Gst.State.NULL)
