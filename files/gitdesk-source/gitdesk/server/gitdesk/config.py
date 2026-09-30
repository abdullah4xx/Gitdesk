from dataclasses import dataclass


@dataclass
class Config:
    port: int = 12345              # TCP port (host listens, device connects via `adb reverse`)
    width: int = 1280              # default tuned for Galaxy Tab A7 (Snapdragon 662); 0 => match device
    height: int = 800
    max_long_side: int = 1920      # cap used when width/height are 0 (auto)
    fps: int = 60
    bitrate_kbps: int = 5000
    min_bitrate_kbps: int = 1000
    max_bitrate_kbps: int = 6000   # hard cap, also applied to live bitrate requests from the phone
    h264_profile: str = "main"     # H.264/AVC only — never HEVC; "main" is the safest for mobile HW decoders
    encoder: str = "auto"          # auto | nvenc | vah264 | vaapi | x264
    adb_serial: str = ""           # "" => first ready device
    package: str = "dev.gitdesk.client"
    activity: str = ".MainActivity"
    auto_launch: bool = True
