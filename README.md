# 🖥️ GitDesk

**GitDesk** is a fast, lightweight solution designed to turn any Android phone or tablet into a **full-featured secondary display** and touch control interface for **Linux**, connected directly via USB cable for ultra-low latency performance.

## 📸 Screenshots

| Android Client | Linux Host |
| :---: | :---: |
| *(Add App Screenshot)* | *(Add Desktop Screenshot)* |

## ✨ Key Features

* **⚡ Ultra-Low Latency Wired Connection:** High-speed streaming and touch responsiveness over a direct USB connection—no local Wi-Fi or cellular network required.
* **🎬 Hardware-Accelerated Decoding:** Advanced H.264/AVC decoding support ensuring smooth playback and low power consumption across both high-end and budget Android devices.
* **🔄 Zero-Freeze Streaming:** Resolved frame-drop and stream-freezing issues (0 FPS bugs) for rock-solid, long-duration stability.
* **🎨 Modern User Interface:** Features an interactive floating toolbar menu for quick-access commands alongside slick loading overlays.

## 📦 Downloads

You can download the latest pre-built binaries directly from the [Releases](../../releases) section:

* 📱 **Android Client:** [`GitDesk.apk`](../../releases/latest/download/GitDesk.apk)
* 🐧 **Linux Host:** [`GitDesk.deb`](../../releases/latest/download/GitDesk.deb)

## 🚀 Setup & Usage Guide

### 1️⃣ Prepare the Android Device (Client)

1. Download and install **`GitDesk.apk`** on your Android device.
2. Go to **Settings** -> **About Phone**.
3. Tap **Build Number** 7 times to enable **Developer Options**.
4. Open **Developer Options** and enable **USB Debugging**.

### 2️⃣ Prepare the Linux Host (Server)

1. Download the **`GitDesk.deb`** package on your Linux system.
2. Open a terminal in the download folder and install the package:
   ```bash
   sudo dpkg -i GitDesk.deb
   ```
3. Ensure ADB tools are installed for wired device communication:
   ```bash
   sudo apt update
   sudo apt install adb
   ```

### 3️⃣ Connect & Start Displaying

1. Connect your Android device to your Linux host using a USB cable.
2. Accept the **"Allow USB Debugging?"** prompt on your Android device.
3. Open the **GitDesk** app on your Android device.
4. Launch the GitDesk server on Linux from your application menu or via terminal:
   ```bash
   gitdesk
   ```
5. The application will automatically detect your device and initiate the high-speed display stream!

## 🛠️ Tech Stack

* **Linux Host:** Python / PipeWire / FFmpeg / ADB Bridge
* **Android Client:** Kotlin / Jetpack Compose / MediaCodec API (H.264)

## 📜 License

This project is open-source and available under the **MIT License**.