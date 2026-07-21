#!/usr/bin/env python3
"""
줌 드리프트 보정 — AI 생성 클립의 자동 줌인을 상쇄해 첫/끝 프레임 크기를 맞춘다.

배경: Grok은 `no zoom` 지시를 무시하고 클립 내내 서서히 줌인한다.
      그 결과 마지막 프레임이 첫 프레임보다 확대되어 하드 루프가 튄다.
      (실측: 첫/끝 PSNR 26dB — 40dB 이상이어야 이음새가 안 보임)

원리: ORB 특징점으로 프레임별 확대율 s(t)를 측정 → 역수만큼 디지털 줌을 걸어
      화면상 크기를 일정하게 만든다. 시작부가 s(T)배 크롭되므로 그만큼 해상도를 손해 본다.

사용법
------
# 1) 측정만 (얼마나 줌인됐는지 확인)
python dezoom.py measure input.mp4

# 2) 보정 실행
python dezoom.py fix input.mp4 -o output.mp4

# 3) 보정 + 배율 수동 지정 (측정이 불안정할 때)
python dezoom.py fix input.mp4 -o output.mp4 --zoom 1.12

의존성: opencv-python, numpy, ffmpeg
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np


def read_frames(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        sys.exit(f"[에러] 프레임을 읽지 못했습니다: {path}")
    return frames, fps


def scale_between(ref_gray, cur_gray, orb, matcher):
    """ref 대비 cur의 확대율. 실패 시 None."""
    k1, d1 = orb.detectAndCompute(ref_gray, None)
    k2, d2 = orb.detectAndCompute(cur_gray, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return None
    matches = matcher.match(d1, d2)
    if len(matches) < 8:
        return None
    matches = sorted(matches, key=lambda m: m.distance)[:120]
    src = np.float32([k1[m.queryIdx].pt for m in matches])
    dst = np.float32([k2[m.trainIdx].pt for m in matches])
    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                       ransacReprojThreshold=3.0)
    if M is None:
        return None
    # partial affine = [s*cos, -s*sin; s*sin, s*cos] → s = sqrt(det)
    det = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
    if det <= 0:
        return None
    return float(np.sqrt(det))


def measure(frames, step=5):
    """프레임별 확대율 곡선을 측정하고 (배율리스트, 최종배율) 반환."""
    orb = cv2.ORB_create(1500)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ref = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)

    idx, vals = [0], [1.0]
    for i in range(step, len(frames), step):
        s = scale_between(ref, cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY), orb, matcher)
        if s is not None and 0.5 < s < 3.0:
            idx.append(i)
            vals.append(s)
    if len(idx) < 3:
        return None, None
    # 마지막 프레임까지 선형 외삽으로 채움
    curve = np.interp(np.arange(len(frames)), idx, vals)
    return curve, float(curve[-1])


def apply_fix(frames, curve, out_path, fps):
    """s(t)의 역수만큼 디지털 줌 → 화면상 크기 일정화."""
    h, w = frames[0].shape[:2]
    Z = float(curve.max())
    tmp = Path(tempfile.gettempdir()) / "_dezoom_raw.mp4"
    vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i, f in enumerate(frames):
        z = Z / max(curve[i], 1e-6)          # t=0에서 Z, t=T에서 1
        cw, ch = int(round(w / z)), int(round(h / z))
        cw, ch = max(cw, 8), max(ch, 8)
        x, y = (w - cw) // 2, (h - ch) // 2
        crop = f[y:y + ch, x:x + cw]
        vw.write(cv2.resize(crop, (w, h), interpolation=cv2.INTER_LANCZOS4))
    vw.release()
    subprocess.run(["ffmpeg", "-y", "-i", str(tmp), "-an",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out_path), "-loglevel", "error"], check=True)
    tmp.unlink(missing_ok=True)


def psnr_first_last(frames):
    a = frames[0].astype(np.float64)
    b = frames[-1].astype(np.float64)
    mse = np.mean((a - b) ** 2)
    return float("inf") if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def main():
    p = argparse.ArgumentParser(description="AI 클립의 줌 드리프트 보정")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure", help="줌 드리프트 측정만")
    m.add_argument("input")

    f = sub.add_parser("fix", help="줌 보정 실행")
    f.add_argument("input")
    f.add_argument("-o", "--output", required=True)
    f.add_argument("--zoom", type=float, default=None,
                   help="총 확대율 수동 지정 (측정이 불안정할 때, 예: 1.12)")

    a = p.parse_args()
    frames, fps = read_frames(a.input)
    print(f"[정보] {len(frames)}프레임 / {fps:.1f}fps / {frames[0].shape[1]}x{frames[0].shape[0]}")
    print(f"[측정] 보정 전 첫-끝 PSNR: {psnr_first_last(frames):.2f} dB")

    if a.cmd == "measure":
        curve, total = measure(frames)
        if curve is None:
            print("[경고] 특징점이 부족해 측정 실패. --zoom 으로 수동 지정하세요.")
            return
        print(f"[측정] 총 확대율: {total:.4f}  (=마지막이 첫 프레임보다 {(total-1)*100:.1f}% 확대)")
        print(f"[측정] 보정 시 시작부 손실: 약 {(1-1/total)*100:.1f}%")
        return

    if a.zoom:
        curve = np.linspace(1.0, a.zoom, len(frames))
        print(f"[설정] 수동 배율 {a.zoom:.4f} (선형 가정)")
    else:
        curve, total = measure(frames)
        if curve is None:
            sys.exit("[에러] 측정 실패. --zoom 으로 수동 지정하세요.")
        print(f"[측정] 총 확대율: {total:.4f}")

    apply_fix(frames, curve, a.output, fps)
    out_frames, _ = read_frames(a.output)
    print(f"[결과] 보정 후 첫-끝 PSNR: {psnr_first_last(out_frames):.2f} dB")
    print(f"[완료] -> {a.output}")


if __name__ == "__main__":
    main()
