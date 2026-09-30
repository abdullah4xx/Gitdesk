"""GitDesk wire protocol v1.

Every message, in both directions:  [type:u8][len:u32 BE][payload:len bytes]

Server -> client
  HELLO  payload: "GD" magic, version u8, width u16, height u16, fps u8, codec u8 (1 = H.264)
  VIDEO  payload: flags u8 (bit0 = keyframe), pts_us u64, then one Annex-B access unit
  PING   payload: server monotonic timestamp u64 (us)
  BYE    payload: empty
  STATS  payload: fps*10 u16, kbps u32, rtt_ms*10 u16, target_kbps u32   (sent once per second)
Client -> server
  PONG         payload: echo of PING payload (8 bytes)
  REQ_IDR      payload: empty (ask for a keyframe, e.g. after decoder reset)
  SET_BITRATE  payload: kbps u32 (clamped server-side to [min, max])
  TOUCH / KEY: defined in Part 3 (input protocol)
"""
import struct
import time

VERSION = 1
CODEC_H264 = 1

T_HELLO, T_VIDEO, T_PING, T_BYE, T_STATS = 0x01, 0x02, 0x03, 0x04, 0x05
T_TOUCH, T_PONG, T_KEY, T_REQ_IDR, T_SET_BITRATE = 0x10, 0x11, 0x12, 0x13, 0x14

_HDR = struct.Struct("!BI")
_HELLO = struct.Struct("!2sBHHBB")
_VIDEO = struct.Struct("!BQ")
_STATS = struct.Struct("!HIHI")
_TS = struct.Struct("!Q")
_U32 = struct.Struct("!I")
MAX_PAYLOAD = 16 << 20


def now_us() -> int:
    return time.monotonic_ns() // 1000


def pack(t: int, payload: bytes = b"") -> bytes:
    return _HDR.pack(t, len(payload)) + payload


def pack_hello(w: int, h: int, fps: int) -> bytes:
    return pack(T_HELLO, _HELLO.pack(b"GD", VERSION, w, h, fps, CODEC_H264))


def pack_video(data: bytes, keyframe: bool, pts_us: int) -> bytes:
    # single join => one copy of the access unit
    return b"".join((_HDR.pack(T_VIDEO, _VIDEO.size + len(data)),
                     _VIDEO.pack(1 if keyframe else 0, pts_us), data))


def pack_ping() -> bytes:
    return pack(T_PING, _TS.pack(now_us()))


def pack_stats(fps: float, kbps: float, rtt_ms: float, target_kbps: int) -> bytes:
    return pack(T_STATS, _STATS.pack(min(int(fps * 10), 65535), int(kbps),
                                     min(int(rtt_ms * 10), 65535), int(target_kbps)))


def unpack_ts(payload: bytes) -> int:
    return _TS.unpack(payload[:8])[0]


def unpack_u32(payload: bytes) -> int:
    return _U32.unpack(payload[:4])[0]


def recv_exact(sock, n: int) -> bytes:
    buf = bytearray(n)
    view, got = memoryview(buf), 0
    while got < n:
        r = sock.recv_into(view[got:], n - got)
        if not r:
            raise ConnectionError("peer closed")
        got += r
    return bytes(buf)


def recv_frame(sock):
    t, n = _HDR.unpack(recv_exact(sock, _HDR.size))
    if n > MAX_PAYLOAD:
        raise ValueError("oversized frame")
    return t, (recv_exact(sock, n) if n else b"")
