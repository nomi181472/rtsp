#!/usr/bin/env python3
"""
Entrypoint and dynamic orchestrator for Mock Hikvision CCTV RTSP Server.
Reads streams.json, validates local and CDN sources, builds MediaMTX configuration,
hosts the multi-view CCTV web station, and runs the RTSP / WebRTC server.
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

IS_WINDOWS = os.name == "nt"

# Media files picked up by the videos/ auto-discovery scan.
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".flv")

# Prefixes expanded into readable words when naming auto-discovered channels.
CAMERA_NAME_TOKENS = {
    "cam": "Camera",
    "ch": "Channel",
    "chan": "Channel",
    "channel": "Channel",
    "clip": "Clip",
    "footage": "Footage",
    "vid": "Video",
    "video": "Video",
}

REMOTE_SOURCE_PREFIXES = ("http://", "https://", "rtsp://", "rtmp://", "srt://")


def find_mediamtx_binary() -> str:
    """Locate the mediamtx binary in PATH, local bin/, or /usr/local/bin."""
    bin_dir = Path(__file__).resolve().parent.parent / "bin"
    exe_name = "mediamtx.exe" if IS_WINDOWS else "mediamtx"

    candidates = [
        os.environ.get("MEDIAMTX_PATH"),
        str(bin_dir / exe_name),
        str(bin_dir / "mediamtx"),
        "/usr/local/bin/mediamtx",
        "/app/bin/mediamtx",
        exe_name,
        "mediamtx",
    ]
    for c in candidates:
        if not c:
            continue
        if os.path.isfile(c) and (IS_WINDOWS or os.access(c, os.X_OK)):
            return str(Path(c).resolve())
        found = shutil.which(c)
        if found:
            return str(Path(found).resolve())
    raise FileNotFoundError("Could not find executable 'mediamtx' binary.")


def find_font_file() -> Optional[str]:
    """Return an absolute path to a usable TrueType font for ffmpeg drawtext."""
    if IS_WINDOWS:
        candidates = [
            os.environ.get("WINDIR", "C:\\Windows") + r"\Fonts\arial.ttf",
            os.environ.get("WINDIR", "C:\\Windows") + r"\Fonts\segoeui.ttf",
            os.environ.get("WINDIR", "C:\\Windows") + r"\Fonts\consola.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
        ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def render_fontfile_option() -> str:
    """Build a fontfile= filter option for the platform, forward-slashed for ffmpeg."""
    font_file = find_font_file()
    if not font_file:
        return ""
    # Forward slashes avoid filtergraph escaping issues with Windows drive colons.
    return f"fontfile={font_file.replace(os.sep, '/')}:"


def get_additional_hosts() -> List[str]:
    """Discover host IPs for WebRTC ICE candidate negotiation."""
    hosts = ["localhost", "127.0.0.1"]

    # Always auto-detect primary LAN IP on the local network/router
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        if lan_ip and lan_ip not in hosts:
            hosts.append(lan_ip)
    except Exception:
        pass

    # Merge any explicit hosts from environment variable
    env_hosts = os.environ.get("WEBRTC_ADDITIONAL_HOSTS", "").strip()
    if env_hosts:
        for h in env_hosts.split(","):
            h = h.strip()
            if h and h not in hosts:
                hosts.append(h)

    return hosts


def build_channels_api_payload(
    server_opts: Dict[str, Any], report: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Build the /api/channels payload so the dashboard never hardcodes channels."""
    return {
        "rtsp_port": server_opts["rtsp_port"],
        "hls_port": server_opts["hls_port"],
        "webrtc_port": server_opts["webrtc_port"],
        "web_port": server_opts["web_port"],
        "api_port": server_opts["api_port"],
        "channels": [
            {
                "id": item["id"],
                "name": item["name"],
                "type": item["type"],
                "source": item["source"],
                "description": item.get("description", ""),
                "live_timestamp": item["live_timestamp"],
                "res": item.get("res", ""),
                "fps": item.get("fps", ""),
                "direct_path": item["direct_path"],
                "hik_path": item["hik_path"],
                "legacy_path": item["legacy_path"],
            }
            for item in report
        ],
    }


def start_web_dashboard(web_dir: Path, port: int, api_payload: Optional[Dict[str, Any]] = None) -> Any:
    """Run lightweight HTTP server for CCTV Multi-View Web Dashboard."""
    if not web_dir.exists():
        print(f"[WARN] Web dashboard directory not found at: {web_dir}")
        return None

    channels_json = json.dumps(api_payload or {"channels": []}).encode("utf-8")

    class QuietHTTPHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def _send_json(self, body: bytes, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?", 1)[0].rstrip("/") == "/api/channels":
                self._send_json(channels_json)
                return
            if self.path.startswith("/api/delay"):
                import time
                time.sleep(3.5)
                self._send_json(b"", 200)
                return
            super().do_GET()

        def log_message(self, format, *args):
            pass  # Suppress routine GET request spam

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), QuietHTTPHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"[INIT] CCTV Web Multi-View Dashboard started on http://0.0.0.0:{port}")
        return httpd
    except Exception as e:
        print(f"[WARN] Could not start web dashboard on port {port}: {e}")
        return None


def coerce_bool(value: Any, default: bool) -> bool:
    """Parse a boolean that may arrive as a real bool, a number, or a string."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return default


def resolve_local_path(source: str, base_dir: Path) -> Optional[Path]:
    """Return the absolute path of a local source, or None for remote URLs."""
    if not source or source.lower().startswith(REMOTE_SOURCE_PREFIXES):
        return None
    path = Path(source)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def prettify_channel_name(stem: str) -> str:
    """Turn a video filename stem into a readable camera name (cam909 -> Camera 909)."""
    trailing = re.search(r"(\d+)$", stem)
    digits = trailing.group(1) if trailing else ""
    base = stem[: len(stem) - len(digits)] if digits else stem

    words = [w for w in re.split(r"[^0-9A-Za-z]+", base) if w]
    label = " ".join(CAMERA_NAME_TOKENS.get(w.lower(), w.capitalize()) for w in words)

    if digits:
        return f"{label} {digits}".strip()
    return label or "Camera"


def allocate_next_channel_id(used_ids: Set[str]) -> str:
    """Return the next free Hikvision-style channel ID (101, 202, 303, ...)."""
    for n in range(1, 10):
        candidate = f"{n}{n:02d}"
        if candidate not in used_ids:
            return candidate
    return str(1000 + len(used_ids))


def discover_video_channels(
    base_dir: Path,
    existing_channels: List[Dict[str, Any]],
    videos_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Scan the videos directory and build channels for files not yet configured."""
    vdir = Path(videos_dir) if videos_dir else (base_dir / "videos")
    if not vdir.is_dir():
        return []

    used_ids = {str(ch["id"]) for ch in existing_channels}
    referenced: Set[Path] = set()
    for ch in existing_channels:
        local = resolve_local_path(ch.get("source", ""), base_dir)
        if local is not None:
            referenced.add(local)

    media_files = sorted(
        (p for p in vdir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )
    unclaimed = [p for p in media_files if p.resolve() not in referenced]

    # Two passes so that filename-derived IDs always win: cam101.mp4 must claim
    # 101 before a digit-less blur_car.mp4 is handed the next free ID.
    with_digits = [p for p in unclaimed if re.search(r"(\d+)", p.stem)]
    without_digits = [p for p in unclaimed if not re.search(r"(\d+)", p.stem)]

    discovered: List[Dict[str, Any]] = []
    for media in with_digits:
        ch_id = re.search(r"(\d+)", media.stem).group(1)
        if ch_id in used_ids:
            print(
                f"[WARN] Skipping {media.name}: channel ID {ch_id} is already used "
                f"by another source. Rename the file or free that ID."
            )
            continue
        used_ids.add(ch_id)
        discovered.append(_build_discovered_channel(media, ch_id))

    for media in without_digits:
        ch_id = allocate_next_channel_id(used_ids)
        used_ids.add(ch_id)
        discovered.append(_build_discovered_channel(media, ch_id))

    return discovered


def _build_discovered_channel(media: Path, ch_id: str) -> Dict[str, Any]:
    """Create a channel definition for an auto-discovered video file."""
    print(f"[AUTO] Discovered videos/{media.name} -> channel {ch_id}")
    return {
        "id": ch_id,
        "name": prettify_channel_name(media.stem),
        "source": f"./videos/{media.name}",
        "description": "Auto-discovered local video file",
    }


def persist_discovered_channels(config_path: Path, new_channels: List[Dict[str, Any]]) -> bool:
    """Append auto-discovered channels back into streams.json (best effort, atomic)."""
    if not new_channels:
        return False

    tmp_path = config_path.with_name(config_path.name + ".tmp")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            doc = json.load(f)

        if not isinstance(doc, dict) or not isinstance(doc.get("channels"), list):
            print("[WARN] streams.json has no 'channels' array; not persisting discovered channels.")
            return False

        for ch in new_channels:
            doc["channels"].append({k: ch[k] for k in ("id", "name", "source", "description")})

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, config_path)

        print(f"[AUTO] Persisted {len(new_channels)} new channel(s) to {config_path}")
        return True
    except Exception as e:
        print(f"[WARN] Could not persist discovered channels to {config_path}: {e}")
        print("[WARN] Continuing with in-memory channels only (is the mount read-only?).")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def probe_video_meta(path: str) -> Dict[str, str]:
    """Best-effort resolution/fps probe for dashboard display only."""
    if not shutil.which("ffprobe"):
        return {}
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate",
                "-of", "json", path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return {}
        streams = json.loads(result.stdout or "{}").get("streams") or []
        stream = streams[0] if streams else {}
    except Exception:
        return {}

    meta: Dict[str, str] = {}
    width, height = stream.get("width"), stream.get("height")
    if width and height:
        # Standard labels are based on the short edge: 1920x1080 -> 1080p.
        meta["res"] = f"{height}p" if width >= height else f"{width}p"

    frame_rate = stream.get("avg_frame_rate") or ""
    try:
        num, den = (int(part) for part in frame_rate.split("/"))
        if num > 0 and den > 0:
            meta["fps"] = f"{round(num / den)} FPS"
    except Exception:
        pass

    return meta


def load_streams_config(
    config_path: Path,
    base_dir: Path,
    apply_discovery: bool = True,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Parse streams.json supporting multiple flexible schema variants."""
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    server_opts = {
        "rtsp_port": int(os.environ.get("RTSP_PORT", 8554)),
        "hls_port": int(os.environ.get("HLS_PORT", 8888)),
        "webrtc_port": int(os.environ.get("WEBRTC_PORT", 8889)),
        "web_port": int(os.environ.get("WEB_PORT", 8080)),
        "api_port": int(os.environ.get("API_PORT", 9997)),
        "log_level": os.environ.get("LOG_LEVEL", "info"),
        "live_timestamp": coerce_bool(os.environ.get("LIVE_TIMESTAMP", "true"), True),
        "username": os.environ.get("RTSP_USERNAME", "admin"),
        "password": os.environ.get("RTSP_PASSWORD", "Password123"),
        "auto_discover": coerce_bool(os.environ.get("AUTO_DISCOVER", "true"), True),
        "videos_dir": os.environ.get("VIDEOS_DIR", ""),
    }
    channels: List[Dict[str, Any]] = []

    if isinstance(raw, dict):
        if "server" in raw and isinstance(raw["server"], dict):
            for k, v in raw["server"].items():
                if k in server_opts and v is not None:
                    if isinstance(server_opts[k], bool):
                        server_opts[k] = coerce_bool(v, server_opts[k])
                    else:
                        server_opts[k] = type(server_opts[k])(v)

        raw_channels = raw.get("channels", raw.get("streams", []))
        if isinstance(raw_channels, list):
            for ch in raw_channels:
                if isinstance(ch, dict) and ("id" in ch or "channel" in ch):
                    ch_id = str(ch.get("id", ch.get("channel")))
                    channels.append({
                        "id": ch_id,
                        "name": ch.get("name", f"Camera {ch_id}"),
                        "source": ch.get("source", ch.get("url", ch.get("path", ""))),
                        "description": ch.get("description", ""),
                        "live_timestamp": ch.get("live_timestamp", server_opts["live_timestamp"]),
                    })
        elif isinstance(raw_channels, dict):
            for ch_id, ch_val in raw_channels.items():
                if isinstance(ch_val, dict):
                    channels.append({
                        "id": str(ch_id),
                        "name": ch_val.get("name", f"Camera {ch_id}"),
                        "source": ch_val.get("source", ch_val.get("url", "")),
                        "description": ch_val.get("description", ""),
                        "live_timestamp": ch_val.get("live_timestamp", server_opts["live_timestamp"]),
                    })
                elif isinstance(ch_val, str):
                    channels.append({
                        "id": str(ch_id),
                        "name": f"Camera {ch_id}",
                        "source": ch_val,
                        "description": "",
                        "live_timestamp": server_opts["live_timestamp"],
                    })
        else:
            for k, v in raw.items():
                if k != "server" and isinstance(v, str):
                    channels.append({
                        "id": str(k),
                        "name": f"Camera {k}",
                        "source": v,
                        "description": "",
                        "live_timestamp": server_opts["live_timestamp"],
                    })

    elif isinstance(raw, list):
        for ch in raw:
            if isinstance(ch, dict):
                ch_id = str(ch.get("id", ch.get("channel", len(channels) + 1)))
                channels.append({
                    "id": ch_id,
                    "name": ch.get("name", f"Camera {ch_id}"),
                    "source": ch.get("source", ch.get("url", ch.get("path", ""))),
                    "description": ch.get("description", ""),
                    "live_timestamp": ch.get("live_timestamp", server_opts["live_timestamp"]),
                })

    if apply_discovery and server_opts.get("auto_discover", True):
        videos_dir = Path(server_opts["videos_dir"]) if server_opts.get("videos_dir") else None
        discovered = discover_video_channels(base_dir, channels, videos_dir)
        if discovered:
            channels.extend(discovered)
            persist_discovered_channels(config_path, discovered)
            server_opts["_discovery_applied"] = True

    return server_opts, channels


def resolve_source(source: str, base_dir: Path) -> Tuple[str, str]:
    """Determine if source is a remote CDN/object URL or local file path."""
    if source.lower().startswith(REMOTE_SOURCE_PREFIXES):
        return source, "Remote CDN / Object URL"

    p = Path(source)
    if not p.is_absolute():
        p = (base_dir / p).resolve()

    if not p.exists():
        videos_alt = (base_dir / "videos" / p.name).resolve()
        if videos_alt.exists():
            p = videos_alt
        else:
            print(f"[WARN] Local video file not found yet: {p}. Attempting sample generation...")
            try:
                if str(base_dir) not in sys.path:
                    sys.path.insert(0, str(base_dir))
                from app.generate_sample_videos import generate_cctv_video
                generate_cctv_video(p, camera_name=f"CAM-{p.stem}", channel_id=p.stem, duration=10)
            except Exception as e:
                print(f"[WARN] Could not auto-generate sample video for {p}: {e}")

    return str(p), "Local Video File"


def build_mediamtx_yaml(server_opts: Dict[str, Any], channels: List[Dict[str, Any]], base_dir: Path) -> Tuple[str, List[Dict[str, str]]]:
    """Generate MediaMTX YAML configuration mapping each channel to RTSP, WebRTC, and HLS."""
    rtsp_port = server_opts["rtsp_port"]
    hls_port = server_opts["hls_port"]
    webrtc_port = server_opts["webrtc_port"]
    web_port = server_opts["web_port"]
    api_port = server_opts["api_port"]
    log_level = server_opts["log_level"]

    username = server_opts.get("username", "").strip()
    password = server_opts.get("password", "").strip()

    hosts_list = get_additional_hosts()
    hosts_yaml = "[" + ", ".join(f'"{h}"' for h in hosts_list) + "]"

    yaml_lines = [
        "###############################################",
        "# Auto-generated MediaMTX CCTV Configuration",
        "###############################################",
        f"logLevel: {log_level}",
        "logDestinations: [stdout]",
        f"rtspAddress: :{rtsp_port}",
        "rtpAddress: :8000",
        "rtcpAddress: :8001",
        f"hlsAddress: :{hls_port}",
        "hlsAlwaysRemux: yes",
        'hlsAllowOrigins: ["*"]',
        f"webrtcAddress: :{webrtc_port}",
        "webrtcLocalUDPAddress: :8189",
        "webrtcLocalTCPAddress: :8189",
        f"webrtcAdditionalHosts: {hosts_yaml}",
        'webrtcAllowOrigins: ["*"]',
    ]

    stun_server = os.environ.get("WEBRTC_STUN_SERVER", "").strip()
    if stun_server and stun_server.lower() != "none":
        yaml_lines.extend([
            "webrtcICEServers2:",
            f"  - url: {stun_server}",
        ])
    else:
        yaml_lines.append("webrtcICEServers2: []")

    yaml_lines.extend([
        "webrtcHandshakeTimeout: 10s",
        "webrtcTrackGatherTimeout: 2s",
        f"apiAddress: :{api_port}",
        "api: yes",
        "authMethod: internal",
        "authInternalUsers:",
    ])

    if username and password:
        yaml_lines.extend([
            "  # Allow internal localhost publisher (FFmpeg)",
            "  - user: any",
            "    pass: \"\"",
            "    ips: [\"127.0.0.1\", \"::1\"]",
            "    permissions:",
            "      - action: publish",
            "  # Authenticated CCTV client user",
            f"  - user: {username}",
            f"    pass: \"{password}\"",
            "    ips: []",
            "    permissions:",
            "      - action: read",
            "      - action: playback",
            "      - action: api",
        ])
    else:
        yaml_lines.extend([
            "  - user: any",
            "    pass: \"\"",
            "    ips: []",
            "    permissions:",
            "      - action: api",
            "      - action: read",
            "      - action: publish",
            "      - action: playback",
        ])

    yaml_lines.extend(["", "paths:"])

    report = []
    user_prefix = f"{username}:{password}@" if (username and password) else ""

    for ch in channels:
        ch_id = ch["id"]
        ch_name = ch["name"]
        raw_source = ch["source"]
        resolved_src, src_type = resolve_source(raw_source, base_dir)

        ch_num = "".join(filter(str.isdigit, ch_id)) or ch_id
        if len(ch_num) >= 3 and ch_num.endswith("01"):
            legacy_ch_num = ch_num[:-2] or "1"
        elif len(ch_num) >= 3 and ch_num.endswith("02"):
            legacy_ch_num = ch_num[:-2] or "1"
        else:
            legacy_ch_num = ch_num

        direct_path = ch_id
        hik_path = f"Streaming/Channels/{ch_id}"
        legacy_path = f"ch{legacy_ch_num}/main/av_stream"

        use_timestamp = ch.get("live_timestamp", server_opts.get("live_timestamp", True))

        # Use TCP interleaved RTSP transport to prevent UDP packet loss and FU-A errors
        tee_target = (
            f"[f=rtsp:rtsp_transport=tcp]rtsp://127.0.0.1:{rtsp_port}/{direct_path}|"
            f"[f=rtsp:rtsp_transport=tcp]rtsp://127.0.0.1:{rtsp_port}/{hik_path}|"
            f"[f=rtsp:rtsp_transport=tcp]rtsp://127.0.0.1:{rtsp_port}/{legacy_path}"
        )

        if use_timestamp:
            safe_name = ch_name.replace("'", "")
            font_opt = render_fontfile_option()
            filter_str = (
                f"drawbox=y=0:h=46:color=black@0.5:t=fill,"
                f"drawtext={font_opt}text='[HIKVISION] {safe_name} (CH-{ch_id})':x=20:y=12:fontsize=22:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2,"
                f"drawtext={font_opt}text='%{{localtime\\:%Y-%m-%d %T}}':x=w-tw-20:y=12:fontsize=22:fontcolor=yellow:shadowcolor=black:shadowx=2:shadowy=2"
            )
            # Use libopus audio codec so WebRTC browsers (Chrome/Firefox/Safari) can play audio without dropping track
            ffmpeg_cmd = (
                f'ffmpeg -re -stream_loop -1 -i "{resolved_src}" '
                f'-vf "{filter_str}" '
                f'-c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p '
                f'-c:a libopus -b:a 64k '
                f'-f tee -map 0:v -map 0:a? "{tee_target}"'
            )
        else:
            ffmpeg_cmd = (
                f'ffmpeg -re -stream_loop -1 -i "{resolved_src}" '
                f'-c:v copy -c:a libopus -b:a 64k '
                f'-f tee -map 0:v -map 0:a? "{tee_target}"'
            )

        yaml_lines.extend([
            f'  "{direct_path}":',
            f'    runOnInit: >-',
            f'      {ffmpeg_cmd}',
            f'    runOnInitRestart: yes',
            f'  "{hik_path}": {{}}',
            f'  "{legacy_path}": {{}}',
            '',
        ])

        meta = probe_video_meta(resolved_src) if src_type == "Local Video File" else {}

        report.append({
            "id": ch_id,
            "name": ch_name,
            "type": src_type,
            "source": resolved_src,
            "description": ch.get("description", ""),
            "live_timestamp": "ACTIVE (Continuous Real-Time Clock, Never Repeats)" if use_timestamp else "OFF (Stream Copy)",
            "res": meta.get("res", ""),
            "fps": meta.get("fps", ""),
            "direct_path": direct_path,
            "hik_path": hik_path,
            "legacy_path": legacy_path,
            "direct_url": f"rtsp://{user_prefix}<host>:{rtsp_port}/{direct_path}",
            "hikvision_url": f"rtsp://{user_prefix}<host>:{rtsp_port}/{hik_path}",
            "legacy_url": f"rtsp://{user_prefix}<host>:{rtsp_port}/{legacy_path}",
            "hls_url": f"http://<host>:{hls_port}/{direct_path}/",
            "webrtc_url": f"http://<host>:{webrtc_port}/{direct_path}/",
            "web_dashboard": f"http://<host>:{web_port}/",
        })

    yaml_lines.extend([
        "  all_others: {}",
        "",
    ])

    return "\n".join(yaml_lines), report


def print_banner(server_opts: Dict[str, Any], report: List[Dict[str, str]]):
    """Print an ASCII dashboard showing active CCTV channels and URLs."""
    rtsp_port = server_opts["rtsp_port"]
    hls_port = server_opts["hls_port"]
    webrtc_port = server_opts["webrtc_port"]
    web_port = server_opts["web_port"]
    username = server_opts.get("username", "")
    password = server_opts.get("password", "")

    print("\n" + "=" * 80)
    print("      HIKVISION MOCK CCTV RTSP SERVER (MediaMTX + FFmpeg Engine)")
    print("=" * 80)
    print(f" RTSP Port      : {rtsp_port}")
    if username and password:
        print(f" RTSP Auth      : ENABLED (User: {username} | Pass: {password})")
    else:
        print(" RTSP Auth      : DISABLED (Anonymous access)")
    print(f" Web Dashboard  : http://localhost:{web_port}/ (Multi-Camera CCTV Control Station)")
    print(f" WebRTC Player  : http://localhost:{webrtc_port}/<channel>/ (Ultra-Low Latency WHEP)")
    print(f" WebRTC ICE Port: 8189 (UDP & TCP)")
    print(f" HLS Player     : http://localhost:{hls_port}/<channel>/")
    print(f" Auto Discovery : {'ON' if server_opts.get('auto_discover', True) else 'OFF'}"
          f"{' (+new channels added to streams.json)' if server_opts.get('_discovery_applied') else ''}")
    print(f" Channels       : {len(report)} active")
    print("-" * 80)

    for item in report:
        print(f"\n[CAM {item['id']}] {item['name']}")
        print(f"  Source Type   : {item['type']}")
        print(f"  Source Target : {item['source']}")
        print(f"  OSD Clock     : {item['live_timestamp']}")
        print(f"  Direct RTSP   : {item['direct_url']}")
        print(f"  Hikvision URL : {item['hikvision_url']}")
        print(f"  Legacy Hik URL: {item['legacy_url']}")
        print(f"  Web Preview   : {item['webrtc_url']} (WebRTC) | {item['hls_url']} (HLS)")

    print("\n" + "=" * 80)
    print(f" Web Station: http://localhost:{web_port}/  |  RTSP Engine Ready!")
    print("=" * 80 + "\n")


def main():
    base_dir = Path(__file__).resolve().parent.parent
    config_file = Path(os.environ.get("STREAMS_CONFIG_PATH", base_dir / "config" / "streams.json"))

    if not config_file.exists():
        alt_config = base_dir / "streams.json"
        if alt_config.exists():
            config_file = alt_config

    print(f"[INIT] Loading CCTV streams configuration from: {config_file}")
    server_opts, channels = load_streams_config(config_file, base_dir)

    if not channels:
        print("[ERROR] No channels defined in configuration! Exiting.")
        sys.exit(1)

    mediamtx_bin = find_mediamtx_binary()
    print(f"[INIT] Using MediaMTX binary: {mediamtx_bin}")

    config_yaml_content, report = build_mediamtx_yaml(server_opts, channels, base_dir)
    config_yaml_path = Path(tempfile.gettempdir()) / "mediamtx.yml"
    config_yaml_path.write_text(config_yaml_content, encoding="utf-8")

    # Start CCTV Web Dashboard server on web_port
    web_dir = base_dir / "web"
    if not web_dir.exists():
        web_dir = Path("/app/web")
    httpd = start_web_dashboard(web_dir, server_opts["web_port"], build_channels_api_payload(server_opts, report))

    print_banner(server_opts, report)

    # Launch MediaMTX
    popen_kwargs = {}
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([mediamtx_bin, str(config_yaml_path)], **popen_kwargs)

    def terminate_process(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        finally:
            # On Windows TerminateProcess does not kill child processes (e.g. ffmpeg).
            if IS_WINDOWS and proc.poll() is None:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass

    def handle_signal(sig, frame):
        print(f"\n[SHUTDOWN] Received signal {sig}. Stopping CCTV RTSP Server...")
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
        terminate_process(process)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    rc = process.wait()
    if httpd:
        try:
            httpd.shutdown()
        except Exception:
            pass
    sys.exit(rc)


if __name__ == "__main__":
    main()
