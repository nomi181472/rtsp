#!/usr/bin/env python3
"""
Generate realistic mock CCTV videos with security camera OSD (On-Screen Display)
overlays (Camera Name, live timestamp, REC indicator, crosshairs).
"""

import os
import subprocess
import sys
from pathlib import Path


def generate_cctv_video(
    output_path: Path,
    camera_name: str,
    channel_id: str,
    duration: int = 10,
    width: int = 1280,
    height: int = 720,
    fps: int = 25,
):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 1000:
        print(f"[SKIP] Video already exists: {output_path}")
        return

    print(f"[GEN] Generating mock CCTV video: {output_path} ({camera_name})...")

    # Clean mock CCTV surveillance scene:
    # 1. Base video: smptebars with security camera grid & noise
    # 2. Bottom status bar with camera model info
    filters = (
        f"smptebars=size={width}x{height}:rate={fps},"
        f"drawgrid=width=100:height=100:thickness=1:color=white@0.08,"
        f"drawbox=y={height-36}:h=36:color=black@0.7:t=fill,"
        f"drawtext=text='HIKVISION SURVEILLANCE NETWORK | 1080p Stream':x=20:y={height-26}:fontsize=16:fontcolor=lightgrey"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", filters,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-g", str(fps),  # 1 GOP per second for smooth seeking
        "-c:a", "aac",
        "-b:a", "64k",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"[OK] Generated: {output_path} ({output_path.stat().st_size // 1024} KB)")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Failed with custom drawtext, falling back to basic testsrc: {e.stderr.decode()[:200]}")
        # Fallback if fontconfig or drawtext missing
        fallback_cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate={fps}",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(output_path),
        ]
        subprocess.run(fallback_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[OK] Generated fallback: {output_path}")


def main():
    base_dir = Path(__file__).resolve().parent.parent
    videos_dir = base_dir / "videos"

    samples = [
        ("cam101.mp4", "FRONT ENTRANCE GATE", "101"),
        ("cam303.mp4", "OFFICE LOBBY MAIN", "303"),
    ]

    for filename, name, ch_id in samples:
        generate_cctv_video(videos_dir / filename, name, ch_id, duration=8)


if __name__ == "__main__":
    main()
