# GitDesk
Use an Android phone/tablet as a low-latency USB second monitor for Ubuntu/Linux.

## Install
- **Linux:** `sudo apt install ./gitdesk_<ver>_all.deb`, then run `gitdesk`.
- **Android:** open `GitDesk-<ver>.apk` (allow "Install unknown apps").

## Use
1. Phone: enable **USB debugging**, plug in the cable, accept the RSA prompt.
2. PC: run `gitdesk` → **Start streaming** (the app launches automatically).
3. On the phone use the ⋮ button: live FPS / RTT / bitrate (2·4·6 Mbps) and Disconnect.

Defaults are tuned for mid-range tablets (Galaxy Tab A7): H.264 Main profile, 1280×800, 5 Mbps (hard cap 6).

## Troubleshooting
| Symptom | What to do |
|---|---|
| Top bar looks wrong / stale virtual monitor after a crash | `gitdesk --restore-display` |
| Black screen on the device | The app walks a decoder fallback ladder on its own; use **Safe mode** on the error screen if it gives up |
| Picture freezes | The server drops stale frames and resyncs on the next keyframe; if the link is dead it is dropped after 4 s and the phone reconnects |

## Release (maintainers)
`bash scripts/release.sh v0.2.0 "message"` — commits, bumps versions, tags, pushes; CI builds and publishes the .deb + .apk.
Optional signing secrets: `ANDROID_KEYSTORE_B64`, `ANDROID_KS_PASS`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASS`.

## Build locally
- deb: `bash packaging/build-deb.sh`
- apk: `gradle -p android assembleRelease` (JDK 17, Android SDK 34, Gradle 8.7)
