#!/usr/bin/env python3
"""
장면 시퀀스 뮤직비디오 조립 — 하드컷 전용 (크로스페이드 없음)

설계 원칙:
  - **크로스페이드 금지.** 컷은 비트에 맞춰 딱 끊는다. 실제 MV 문법이고,
    페이드는 슬라이드쇼처럼 보인다.
  - 각 컷 안에서는 Ken Burns(느린 줌/팬)로 정지화면 티를 없앤다.
  - 컷 길이는 BPM에서 계산한다 (마디 단위).

사용법
------
# 95 BPM, 2마디(약 5.05초)마다 컷
python build_mv.py --images stills/*.png --bpm 95 --bars 2 -o mv.mp4

# 곡을 얹어 곡 길이만큼 (이미지가 모자라면 순환 사용)
python build_mv.py --images stills/*.png --bpm 95 --bars 2 --audio song.mp3 -o mv.mp4

# Ken Burns 끄기 (완전 정지컷)
python build_mv.py --images stills/*.png --bpm 95 --bars 2 --no-kenburns -o mv.mp4

의존성: opencv-python, numpy, ffmpeg
"""
import argparse
import glob as globmod
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

W, H, FPS = 1920, 1080, 24


def load_fit(path):
    """이미지를 16:9 캔버스에 맞춰 로드 (넘치는 부분은 센터 크롭)."""
    img = cv2.imread(str(path))
    if img is None:
        sys.exit(f"[에러] 이미지를 읽지 못했습니다: {path}")
    ih, iw = img.shape[:2]
    scale = max(W / iw, H / ih) * 1.15          # Ken Burns 여유분 15%
    nw, nh = int(iw * scale), int(ih * scale)
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    return img


def ken_burns_frame(img, t, direction):
    """t: 0~1. 컷 안에서 아주 느린 줌/팬."""
    ih, iw = img.shape[:2]
    z0, z1 = (1.00, 1.06) if direction % 2 == 0 else (1.06, 1.00)
    z = z0 + (z1 - z0) * t
    cw, ch = int(W / z), int(H / z)
    # 방향별로 미세하게 다른 팬
    mx = (iw - cw) * (0.5 + 0.03 * np.sin(direction) * (t - 0.5) * 2)
    my = (ih - ch) * (0.5 + 0.03 * np.cos(direction) * (t - 0.5) * 2)
    x = int(np.clip(mx, 0, iw - cw))
    y = int(np.clip(my, 0, ih - ch))
    return cv2.resize(img[y:y + ch, x:x + cw], (W, H), interpolation=cv2.INTER_LANCZOS4)


def grade(frame):
    """가벼운 필름 질감: 그레인 + 비네트."""
    f = frame.astype(np.float32)
    noise = np.random.normal(0, 3.0, f.shape).astype(np.float32)
    f = np.clip(f + noise, 0, 255)
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = W / 2, H / 2
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    vig = np.clip(1.0 - 0.28 * np.clip(r - 0.55, 0, None) / 0.45, 0, 1)
    f *= vig[..., None]
    return np.clip(f, 0, 255).astype(np.uint8)


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def main():
    ap = argparse.ArgumentParser(description="하드컷 장면 시퀀스 MV 조립")
    ap.add_argument("--images", nargs="+", required=True)
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--bars", type=float, default=2.0, help="컷당 마디 수 (기본 2)")
    ap.add_argument("--beats-per-bar", type=int, default=4)
    ap.add_argument("--audio", default=None)
    ap.add_argument("--no-kenburns", action="store_true")
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args()

    paths = []
    for pat in a.images:
        paths.extend(sorted(globmod.glob(pat)) or [pat])
    if not paths:
        sys.exit("[에러] 이미지를 찾지 못했습니다.")

    shot_sec = a.bars * a.beats_per_bar * 60.0 / a.bpm
    shot_frames = max(1, int(round(shot_sec * FPS)))
    print(f"[정보] {len(paths)}장 / {a.bpm}BPM / {a.bars}마디 = 컷당 {shot_sec:.2f}초")

    if a.audio:
        total = audio_duration(a.audio)
        n_shots = int(np.ceil(total * FPS / shot_frames))
        print(f"[정보] 곡 {total:.1f}초 → 컷 {n_shots}개 (이미지 순환 사용)")
    else:
        n_shots = len(paths)
        print(f"[정보] 총 {n_shots * shot_sec:.1f}초")

    tmp = Path(tempfile.gettempdir()) / "_mv_raw.mp4"
    vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    cache = {}
    for s in range(n_shots):
        p = paths[s % len(paths)]
        if p not in cache:
            cache[p] = load_fit(p)
        img = cache[p]
        for k in range(shot_frames):
            t = k / max(shot_frames - 1, 1)
            f = img[:H, :W] if a.no_kenburns else ken_burns_frame(img, t, s)
            if a.no_kenburns:
                f = cv2.resize(img, (W, H), interpolation=cv2.INTER_LANCZOS4)
            vw.write(grade(f))
        print(f"  컷 {s+1}/{n_shots}  {Path(p).name}")
    vw.release()

    cmd = ["ffmpeg", "-y", "-i", str(tmp)]
    if a.audio:
        cmd += ["-i", str(a.audio), "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            str(a.output), "-loglevel", "error"]
    subprocess.run(cmd, check=True)
    tmp.unlink(missing_ok=True)
    print(f"[완료] -> {a.output}")


if __name__ == "__main__":
    main()
