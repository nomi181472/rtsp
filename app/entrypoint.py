#!/usr/bin/env python3
"""
Entrypoint and dynamic orchestrator for Mock Hikvision CCTV RTSP Server.
Reads streams.json, validates local and CDN sources, builds MediaMTX configuration,
hosts the multi-view CCTV web station, and runs the RTSP / WebRTC server.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple


def find_mediamtx_binary() -> str:
    """Locate the mediamtx binary in PATH, local bin/, or /usr/local/bin."""
    candidates = [
        os.environ.get("MEDIAMTX_PATH"),
        str(Path(__file__).resolve().parent.parent / "bin" / "mediamtx"),
        "/usr/local/bin/mediamtx",
        "/app/bin/mediamtx",
        "mediamtx",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        if c:
            found = subprocess.run(["which", c], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if found.returncode == 0:
                return found.stdout.strip()
    raise FileNotFoundError("Could not find executable 'mediamtx' binary.")


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


def start_web_dashboard(web_dir: Path, port: int) -> Any:
    """Run lightweight HTTP server for CCTV Multi-View Web Dashboard."""
    if not web_dir.exists():
        print(f"[WARN] Web dashboard directory not found at: {web_dir}")
        return None

    class QuietHTTPHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def do_GET(self):
            if self.path.startswith("/api/delay"):
                import time
                time.sleep(3.5)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", "0")
                self.end_headers()
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


def load_streams_config(config_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
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
        "live_timestamp": os.environ.get("LIVE_TIMESTAMP", "true").lower() in ("true", "1", "yes"),
        "username": os.environ.get("RTSP_USERNAME", "admin"),
        "password": os.environ.get("RTSP_PASSWORD", "Password123"),
    }
    channels: List[Dict[str, Any]] = []

    if isinstance(raw, dict):
        if "server" in raw and isinstance(raw["server"], dict):
            for k, v in raw["server"].items():
                if k in server_opts and v is not None:
                    if isinstance(server_opts[k], bool):
                        server_opts[k] = bool(v)
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

    return server_opts, channels


def resolve_source(source: str, base_dir: Path) -> Tuple[str, str]:
    """Determine if source is a remote CDN/object URL or local file path."""
    s_lower = source.lower()
    if s_lower.startswith(("http://", "https://", "rtsp://", "rtmp://", "srt://")):
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
            filter_str = (
                f"drawbox=y=0:h=46:color=black@0.5:t=fill,"
                f"drawtext=text='[HIKVISION] {safe_name} (CH-{ch_id})':x=20:y=12:fontsize=22:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2,"
                f"drawtext=text='%{{localtime\\:%Y-%m-%d %T}}':x=w-tw-20:y=12:fontsize=22:fontcolor=yellow:shadowcolor=black:shadowx=2:shadowy=2"
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

        report.append({
            "id": ch_id,
            "name": ch_name,
            "type": src_type,
            "source": resolved_src,
            "live_timestamp": "ACTIVE (Continuous Real-Time Clock, Never Repeats)" if use_timestamp else "OFF (Stream Copy)",
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
    server_opts, channels = load_streams_config(config_file)

    if not channels:
        print("[ERROR] No channels defined in configuration! Exiting.")
        sys.exit(1)

    mediamtx_bin = find_mediamtx_binary()
    print(f"[INIT] Using MediaMTX binary: {mediamtx_bin}")

    config_yaml_content, report = build_mediamtx_yaml(server_opts, channels, base_dir)
    config_yaml_path = Path("/tmp/mediamtx.yml")
    config_yaml_path.write_text(config_yaml_content, encoding="utf-8")

    # Start CCTV Web Dashboard server on web_port
    web_dir = base_dir / "web"
    if not web_dir.exists():
        web_dir = Path("/app/web")
    httpd = start_web_dashboard(web_dir, server_opts["web_port"])

    print_banner(server_opts, report)

    # Launch MediaMTX
    process = subprocess.Popen([mediamtx_bin, str(config_yaml_path)])

    def handle_signal(sig, frame):
        print(f"\n[SHUTDOWN] Received signal {sig}. Stopping CCTV RTSP Server...")
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
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
