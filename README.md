# 📹 Hikvision Mock CCTV RTSP & WebRTC Server

[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Podman](https://img.shields.io/badge/Podman-Rootless%20Compatible-892CA0?logo=podman&logoColor=white)](https://podman.io/)
[![MediaMTX](https://img.shields.io/badge/MediaMTX-v1.21-00ADD8)](https://github.com/bluenviron/mediamtx)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-v8.1-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![Protocols](https://img.shields.io/badge/Protocols-RTSP%20%7C%20WebRTC%20%7C%20HLS-orange)](https://github.com/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A production-grade, high-performance **Mock Hikvision CCTV RTSP & WebRTC Server** engineered for computer vision developers, QA automation teams, and video management system (VMS) integrations.

It reads streams dynamically from a JSON configuration, loops **local video files** and **remote CDN / Object Storage URLs** indefinitely, burns a **continuous real-time wall-clock timestamp** (which never rewinds across loop transitions), and exposes authentic **Hikvision CCTV RTSP endpoints** alongside an **in-browser WebRTC / HLS control dashboard**.

---

## 🖥️ Live Control Station Dashboard

The server embeds a dark-themed, glassmorphic CCTV multi-view station accessible directly from any web browser:

![Hikvision Mock CCTV Control Station](docs/images/cctv_dashboard_showcase.png)

> **Web Station URL**: [http://localhost:8080/](http://localhost:8080/)  
> *(Pre-configured with credentials `admin` / `Password123`)*

---

## ⚡ Why This Project?

Testing AI computer vision pipelines (YOLO, OpenCV, PyTorch, DeepStream) or configuring NVRs/VMSs (Frigate, Shinobi, Milestone, Home Assistant) usually requires physical IP cameras on your local network. 

This project gives you an **instant, zero-hardware mock surveillance network**:
- **Identical Hikvision URL Formats**: Test against paths your production software expects (`Streaming/Channels/101`, `ch1/main/av_stream`).
- **Continuous Wall-Clock OSD**: Video repeats in a seamless loop, but the on-screen clock counts forward indefinitely using actual system time.
- **Dual Source Support**: Loop local `.mp4` test videos or stream directly from public CDNs and AWS S3/MinIO bucket presigned URLs.
- **Multi-Protocol Delivery**:
  - **RTSP** (Port `8554`) for OpenCV, VLC, NVRs, and AI models.
  - **WebRTC WHEP** (Port `8889` / `8189`) for sub-second (<500ms) browser playback.
  - **HLS** (Port `8888`) for firewall-friendly web streaming.
  - **Web Dashboard** (Port `8080`) for multi-camera live surveillance grid.
- **CCTV Authentication**: Full RTSP/HTTP Basic Auth (`admin` / `Password123`) enabled out-of-the-box.

---

## 📐 Architecture

```
                                 ┌───────────────────────────────┐
                                 │       config/streams.json     │
                                 └──────────────┬────────────────┘
                                                │
                 ┌──────────────────────────────┴──────────────────────────────┐
                 ▼                                                             ▼
       [Local Video Files]                                           [Remote CDN / Cloud URLs]
       ./videos/cam101.mp4                                           https://cdn.example.com/...
                 │                                                             │
                 └──────────────────────────────┬──────────────────────────────┘
                                                │
                                                ▼
                         ┌─────────────────────────────────────────────┐
                         │              FFmpeg Transcoder              │
                         │  - Infinite Loop (-stream_loop -1)          │
                         │  - Real-time OSD Clock (%{localtime:%T})    │
                         │  - H.264 Video (Constrained Baseline)       │
                         │  - Opus Audio (WebRTC / RTSP compliant)     │
                         │  - TCP Interleaved Multiplexing (tee muxer) │
                         └──────────────────────┬──────────────────────┘
                                                │
                                                ▼
                         ┌─────────────────────────────────────────────┐
                         │           MediaMTX Engine v1.21             │
                         │       (RTSP, WebRTC, HLS, REST API)         │
                         └──────────────┬──────────────────────────────┘
                                        │
        ┌───────────────────┬───────────┴───────────┬───────────────────┐
        ▼                   ▼                       ▼                   ▼
   [RTSP Server]     [WebRTC (WHEP)]          [HLS Server]      [Web Dashboard]
   Port: 8554        Port: 8889 / 8189        Port: 8888        Port: 8080
   - /101            - /101/whep              - /101/           - Multi-Cam Grid
   - /Streaming/...  - /202/whep              - /202/           - One-Click Copy
   - /ch1/main/...   - /303/whep              - /303/           - Snapshot Tool
```

---

## 🚀 Quickstart

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & Docker Compose **OR** [Podman](https://podman.io/) (Rootless supported)

### 1. Clone Repository
```bash
git clone https://github.com/your-username/hikvision-mock-cctv.git
cd hikvision-mock-cctv
```

### 2. Start the CCTV Network
```bash
docker compose up -d
```
*(If using Podman, `docker compose up -d` or `podman-compose up -d` works seamlessly).*

### 3. Open Web Dashboard
Navigate to:
👉 **[http://localhost:8080/](http://localhost:8080/)**

### 4. Verify RTSP Health
Run the built-in automated test client:
```bash
python3 test_client.py
```

### 5. Stop the Server
```bash
docker compose down
```

---

## 📺 Sample Camera Feeds

| Channel | Camera Name | Source Type | Sample Live Frame |
|---|---|---|---|
| **101** | Front Entrance Camera | Local MP4 Loop | ![CAM 101 Frame](docs/images/cam101_live_feed.jpg) |
| **202** | Loading Bay / CDN Stream | Remote Cloud CDN | ![CAM 202 Frame](docs/images/cam202_live_feed.jpg) |
| **303** | Office Lobby Camera | Local MP4 Loop | ![CAM 303 Frame](docs/images/cam303_live_feed.jpg) |

---

## 🌐 Endpoints & URL Reference

**Default Credentials**:
- **Username**: `admin`
- **Password**: `Password123`

### 1. RTSP Streams (VLC, FFmpeg, OpenCV, NVRs)

| Channel | Direct URL | Hikvision Standard URL | Legacy Hikvision URL |
| :--- | :--- | :--- | :--- |
| **CAM 101** | `rtsp://admin:Password123@localhost:8554/101` | `rtsp://admin:Password123@localhost:8554/Streaming/Channels/101` | `rtsp://admin:Password123@localhost:8554/ch1/main/av_stream` |
| **CAM 202** | `rtsp://admin:Password123@localhost:8554/202` | `rtsp://admin:Password123@localhost:8554/Streaming/Channels/202` | `rtsp://admin:Password123@localhost:8554/ch2/main/av_stream` |
| **CAM 303** | `rtsp://admin:Password123@localhost:8554/303` | `rtsp://admin:Password123@localhost:8554/Streaming/Channels/303` | `rtsp://admin:Password123@localhost:8554/ch3/main/av_stream` |

### 2. Browser Playback Endpoints

| Protocol | Purpose | URL Format |
| :--- | :--- | :--- |
| **CCTV Web Station** | Multi-camera control room UI | `http://localhost:8080/` |
| **WebRTC Player** | Ultra-low latency single camera | `http://localhost:8889/<channel>/` |
| **HLS Player** | Standard HTTP live streaming | `http://localhost:8888/<channel>/` |
| **REST API** | MediaMTX runtime metrics & paths | `http://localhost:9997/v3/paths/list` |

---

## ⚙️ Configuration (`config/streams.json`)

Configure your server and channels in [`config/streams.json`](config/streams.json). Any changes take effect immediately on container restart:

```json
{
  "server": {
    "rtsp_port": 8554,
    "hls_port": 8888,
    "webrtc_port": 8889,
    "api_port": 9997,
    "log_level": "info",
    "live_timestamp": true,
    "username": "admin",
    "password": "Password123"
  },
  "channels": [
    {
      "id": "101",
      "name": "Front Entrance Camera",
      "source": "./videos/cam101.mp4",
      "description": "Local mock CCTV video looped indefinitely",
      "live_timestamp": true
    },
    {
      "id": "202",
      "name": "Loading Bay / CDN Stream",
      "source": "https://media.w3.org/2010/05/sintel/trailer.mp4",
      "description": "Remote CDN or Cloud Object Storage video URL",
      "live_timestamp": true
    },
    {
      "id": "303",
      "name": "Office Lobby Camera",
      "source": "./videos/cam303.mp4",
      "description": "Secondary local CCTV camera stream",
      "live_timestamp": true
    }
  ]
}
```

### Adding New Cameras
- **Local Video**: Place any `.mp4` / `.mkv` / `.avi` file in `./videos/` and set `"source": "./videos/my_video.mp4"`.
- **Remote CDN / Cloud S3**: Set `"source": "https://s3.amazonaws.com/my-bucket/cctv.mp4"`.

---

## 🛠️ Client Integration Recipes

### 1. Python (OpenCV)
```python
import cv2

# Connect to Hikvision Channel 101 with credentials
RTSP_URL = "rtsp://admin:Password123@localhost:8554/Streaming/Channels/101"

# Force TCP transport for optimal stability
cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("Waiting for stream...")
        continue

    # Process frame (e.g. YOLO detection, motion tracking)
    cv2.imshow("Hikvision Mock CCTV 101", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

### 2. FFplay CLI
```bash
# Play Channel 101 over TCP transport
ffplay -rtsp_transport tcp "rtsp://admin:Password123@localhost:8554/Streaming/Channels/101"

# Play CDN-backed Channel 202
ffplay -rtsp_transport tcp "rtsp://admin:Password123@localhost:8554/202"
```

### 3. VLC Media Player
1. Open VLC Media Player.
2. Select **Media** > **Open Network Stream** (`Ctrl + N`).
3. Enter URL: `rtsp://admin:Password123@localhost:8554/Streaming/Channels/101`.
4. Click **Play**.

### 4. GStreamer Pipeline
```bash
gst-launch-1.0 rtspsrc location="rtsp://admin:Password123@localhost:8554/101" protocols=tcp ! \
  rtph264depay ! h264parse ! avdec_h264 ! autovideosink
```

### 5. Frigate NVR Configuration
```yaml
cameras:
  front_entrance:
    ffmpeg:
      inputs:
        - path: rtsp://admin:Password123@localhost:8554/Streaming/Channels/101
          roles:
            - detect
            - record
    detect:
      width: 1280
      height: 720
      fps: 25
```

---

## 🔌 Port Allocation Matrix

| Port | Protocol | Layer | Purpose |
|---|---|---|---|
| **8554** | TCP | RTSP | Primary RTSP connection & signaling |
| **8000** | UDP | RTP | Audio/Video media data packets |
| **8001** | UDP | RTCP | Real-time transport control protocol |
| **8080** | TCP | HTTP | **CCTV Multi-View Web Dashboard** |
| **8888** | TCP | HTTP | HLS Web Streaming (`/index.m3u8`) |
| **8889** | TCP | HTTP | WebRTC WHEP signaling & native player |
| **8189** | UDP & TCP | ICE | WebRTC media candidate transmission |
| **9997** | TCP | HTTP | MediaMTX REST Management API |

---

## 🧪 Automated Verification Script

An automated test suite [`test_client.py`](test_client.py) is included to validate that all configured channels, paths, and codecs are operating with 100% compliance:

```bash
python3 test_client.py
```

Expected output:
```
=====================================================================================
                      RTSP CCTV STREAM PROBE VERIFICATION
=====================================================================================

[TESTING] Front Entrance Camera [Direct / 101]
 URL: rtsp://admin:Password123@localhost:8554/101
 Status: [PASS] SUCCESS (h264 1280x720, opus)

[TESTING] Front Entrance Camera [Hikvision / 101]
 URL: rtsp://admin:Password123@localhost:8554/Streaming/Channels/101
 Status: [PASS] SUCCESS (h264 1280x720, opus)

[TESTING] Loading Bay / CDN Stream [Direct / 202]
 URL: rtsp://admin:Password123@localhost:8554/202
 Status: [PASS] SUCCESS (h264 854x480, opus)

[TESTING] Loading Bay / CDN Stream [Hikvision / 202]
 URL: rtsp://admin:Password123@localhost:8554/Streaming/Channels/202
 Status: [PASS] SUCCESS (h264 854x480, opus)

[TESTING] Office Lobby Camera [Direct / 303]
 URL: rtsp://admin:Password123@localhost:8554/303
 Status: [PASS] SUCCESS (h264 1280x720, opus)

[TESTING] Office Lobby Camera [Hikvision / 303]
 URL: rtsp://admin:Password123@localhost:8554/Streaming/Channels/303
 Status: [PASS] SUCCESS (h264 1280x720, opus)

=====================================================================================
 ALL PROBED CCTV STREAMS ARE OPERATIONAL AND STREAMING HEALTHY VIDEO!
=====================================================================================
```

---

## 📂 Repository Directory Layout

```
.
├── Dockerfile                  # Multi-stage optimized container definition
├── docker-compose.yml          # Container orchestration with volume mounts
├── .gitignore                  # Clean git exclusion rules
├── README.md                   # Complete documentation
├── test_client.py              # CLI automated RTSP stream validator
├── app/
│   ├── entrypoint.py           # Orchestrator: parses config, launches MediaMTX & Dashboard
│   └── generate_sample_videos.py # Utility to generate synthetic CCTV footage
├── config/
│   └── streams.json            # Dynamic camera channel definitions
├── docs/
│   └── images/                 # Showcase screenshots and live capture feeds
├── videos/                     # Storage directory for local video files
│   ├── cam101.mp4              # Sample camera 101 video
│   └── cam303.mp4              # Sample camera 303 video
└── web/
    ├── index.html              # Modern CCTV Multi-View Web Application
    └── reader.js               # MediaMTX official WHEP WebRTC reader engine
```

---

## ❓ FAQ & Troubleshooting

<details>
<summary><b>1. Why does my video loop, but the timestamp keeps ticking?</b></summary>
The server uses FFmpeg's <code>drawtext</code> filter with the dynamic expansion token <code>%{localtime:%Y-%m-%d %T}</code>. The video decoder runs with <code>-stream_loop -1</code>, but the filter continuously queries the host system's clock on every frame rendered. As a result, the footage repeats smoothly while the OSD timestamp advances continuously.
</details>

<details>
<summary><b>2. How do I change the default username and password?</b></summary>
Set <code>RTSP_USERNAME</code> and <code>RTSP_PASSWORD</code> in your <code>.env</code> file or modify the <code>"server"</code> block in <code>config/streams.json</code>:
<pre>
RTSP_USERNAME=security_admin
RTSP_PASSWORD=MySecretPassword99
</pre>
Restart the container with <code>docker compose down && docker compose up -d</code>.
</details>

<details>
<summary><b>3. Why is WebRTC using Opus instead of AAC?</b></summary>
Web browsers (Chrome, Edge, Safari, Firefox) do not support AAC audio inside WebRTC RTP payloads. The transcode engine converts audio to <b>Opus</b> (64 kbps), which is natively supported by both modern browsers via WebRTC and CCTV clients via RTSP.
</details>

<details>
<summary><b>4. How do I access streams across my local network (LAN)?</b></summary>
Replace <code>localhost</code> with the host machine's LAN IP (e.g. <code>192.168.1.50</code>). The WebRTC ICE layer automatically announces host candidates across your network. Ensure ports <code>8554</code> (RTSP), <code>8080</code> (Web), and <code>8189</code> (WebRTC ICE) are permitted through your firewall.
</details>

---

## 📜 License

Distributed under the **MIT License**. Free for commercial and non-commercial development, automated testing, and research use.
