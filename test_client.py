#!/usr/bin/env python3
"""
Verification and testing client for the Mock Hikvision CCTV RTSP Server.
Probes RTSP streams using ffprobe to confirm live video/audio streaming.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def probe_stream(url: str, timeout: int = 5):
    """Probe an RTSP URL using ffprobe and return stream metadata or error."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-rtsp_transport", "tcp",
        "-timeout", str(timeout * 1000000),  # microseconds in ffprobe rtsp
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate:format=format_name,duration",
        "-of", "json",
        url,
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout + 2)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
            return {
                "ok": True,
                "video": video_stream,
                "audio": audio_stream,
                "format": data.get("format", {}).get("format_name", "rtsp"),
            }
        else:
            return {"ok": False, "error": res.stderr.strip() or "Failed to read stream"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Connection timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Probe and verify RTSP CCTV streams.")
    parser.add_argument("--url", help="Direct RTSP URL to probe (e.g. rtsp://localhost:8554/101)")
    parser.add_argument("--host", default="localhost", help="RTSP server hostname (default: localhost)")
    parser.add_argument("--port", type=int, default=8554, help="RTSP port (default: 8554)")
    parser.add_argument("--config", default="config/streams.json", help="Path to streams.json")
    parser.add_argument("--user", default=None, help="RTSP username")
    parser.add_argument("--password", "--pass", default=None, help="RTSP password")
    parser.add_argument("--timeout", type=int, default=5, help="Probe timeout in seconds (default: 5)")
    args = parser.parse_args()

    urls_to_test = []

    if args.url:
        urls_to_test.append(("Custom URL", args.url))
    else:
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            cfg_path = Path(__file__).resolve().parent / "config" / "streams.json"

        user = args.user
        password = args.password
        port = args.port

        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            channels = data.get("channels", []) if isinstance(data, dict) else data
            server = data.get("server", {}) if isinstance(data, dict) else {}
            port = server.get("rtsp_port", args.port)
            if user is None:
                user = server.get("username")
            if password is None:
                password = server.get("password")

            user_prefix = f"{user}:{password}@" if (user and password) else ""

            for ch in channels:
                ch_id = str(ch.get("id", ch.get("channel", "")))
                name = ch.get("name", f"Camera {ch_id}")
                urls_to_test.append((f"{name} [Direct / {ch_id}]", f"rtsp://{user_prefix}{args.host}:{port}/{ch_id}"))
                urls_to_test.append((f"{name} [Hikvision / {ch_id}]", f"rtsp://{user_prefix}{args.host}:{port}/Streaming/Channels/{ch_id}"))
        else:
            user_prefix = f"{user}:{password}@" if (user and password) else ""
            urls_to_test = [
                ("Default 101 Direct", f"rtsp://{user_prefix}{args.host}:{args.port}/101"),
                ("Default 101 Hikvision", f"rtsp://{user_prefix}{args.host}:{args.port}/Streaming/Channels/101"),
                ("Default 202 Direct", f"rtsp://{user_prefix}{args.host}:{args.port}/202"),
                ("Default 202 Hikvision", f"rtsp://{user_prefix}{args.host}:{args.port}/Streaming/Channels/202"),
            ]

    print("=" * 85)
    print("                      RTSP CCTV STREAM PROBE VERIFICATION")
    print("=" * 85)

    all_passed = True

    for label, url in urls_to_test:
        print(f"\n[TESTING] {label}")
        print(f" URL: {url}")
        result = probe_stream(url, timeout=args.timeout)

        if result["ok"]:
            v = result["video"]
            v_info = f"{v.get('codec_name', 'unknown')} {v.get('width', '?')}x{v.get('height', '?')}" if v else "No video track"
            a = result["audio"]
            a_info = f"{a.get('codec_name', 'none')}" if a else "No audio track"
            print(f" Status: [PASS] SUCCESS")
            print(f" Video : {v_info}")
            print(f" Audio : {a_info}")
        else:
            print(f" Status: [FAIL] ERROR")
            print(f" Detail: {result['error'][:150]}")
            all_passed = False

    print("\n" + "=" * 85)
    if all_passed:
        print(" ALL PROBED CCTV STREAMS ARE OPERATIONAL AND STREAMING HEALTHY VIDEO!")
    else:
        print(" SOME STREAMS FAILED TO RESPOND. Ensure the RTSP server is currently running.")
    print("=" * 85 + "\n")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
