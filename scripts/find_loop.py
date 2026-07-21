#!/usr/bin/env python3
"""
최적 루프 구간 탐색 — 클립 안에서 가장 잘 맞물리는 (시작, 끝) 프레임 쌍을 찾는다.

배경: Grok은 첫 프레임으로 돌아오지 않는다. 하지만 클립 중간 어딘가에
      "서로 닮은 두 프레임"이 있으면 그 구간만 잘라 하드 루프로 쓸 수 있다.

사용법
------
# 후보 탐색 (최소 4초 이상 구간)
python find_loop.py scan input.mp4 --min-sec 4

# 찾은 구간으로 잘라내기
python find_loop.py cut input.mp4 -o loop.mp4 --start 72 --end 288

판정 기준: PSNR 40dB↑ 이음새 안 보임 / 30~35 자세히 보면 보임 / 25~30 명확히 튐
"""
import argparse
import subprocess
import sys

import cv2
import numpy as np


def load_small(path, w=192):
    """속도용 축소 그레이스케일 프레임 + fps 반환."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    small, n = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        n += 1
        h = int(f.shape[0] * w / f.shape[1])
        g = cv2.cvtColor(cv2.resize(f, (w, h)), cv2.COLOR_BGR2GRAY)
        small.append(g.astype(np.float32))
    cap.release()
    if not small:
        sys.exit(f"[에러] 프레임을 읽지 못했습니다: {path}")
    return np.array(small), fps, n


def psnr_matrix(frames, min_gap):
    """모든 (i,j) 쌍의 PSNR. j-i >= min_gap 만 유효."""
    n = len(frames)
    flat = frames.reshape(n, -1)
    # ||a-b||^2 = |a|^2 + |b|^2 - 2a·b
    sq = (flat ** 2).sum(1)
    d2 = sq[:, None] + sq[None, :] - 2 * (flat @ flat.T)
    d2 = np.maximum(d2, 0)
    mse = d2 / flat.shape[1]
    with np.errstate(divide="ignore"):
        p = 10 * np.log10(255.0 ** 2 / np.maximum(mse, 1e-9))
    # 유효 범위 마스킹
    ii, jj = np.indices((n, n))
    p[(jj - ii) < min_gap] = -1
    return p


def scan(path, min_sec, top):
    frames, fps, n = load_small(path)
    print(f"[정보] {n}프레임 / {fps:.1f}fps / {n/fps:.2f}초")
    min_gap = int(min_sec * fps)
    if min_gap >= n:
        sys.exit(f"[에러] --min-sec {min_sec}가 클립 길이보다 깁니다.")

    p = psnr_matrix(frames, min_gap)
    print(f"[참고] 첫-끝 PSNR: {p[0, n-1]:.2f} dB" if p[0, n-1] > 0 else "")

    idx = np.dstack(np.unravel_index(np.argsort(-p, axis=None), p.shape))[0]
    print(f"\n[결과] 최소 {min_sec}초 이상 구간 중 상위 {top}개\n")
    print("  순위   시작→끝(프레임)     길이      PSNR")
    print("  " + "-" * 44)
    seen, cnt = [], 0
    for i, j in idx:
        if p[i, j] <= 0:
            break
        # 이미 뽑은 구간과 너무 겹치면 스킵
        if any(abs(i - a) < fps and abs(j - b) < fps for a, b in seen):
            continue
        seen.append((i, j))
        cnt += 1
        print(f"  {cnt:>2}   {i:>4} → {j:<4}      {(j-i)/fps:>5.2f}초   {p[i,j]:>6.2f} dB")
        if cnt >= top:
            break

    if seen:
        i, j = seen[0]
        print(f"\n[추천] --start {i} --end {j}   ({(j-i)/fps:.2f}초, {p[i,j]:.2f} dB)")
        # 기준선: 인접 프레임 PSNR (필름 그레인 때문에 이게 사실상 천장)
        adj = np.median([
            10 * np.log10(255.0 ** 2 / max(np.mean((frames[k] - frames[k + 1]) ** 2), 1e-9))
            for k in range(0, len(frames) - 1, 7)
        ])
        gap = adj - p[i, j]
        print(f"        노이즈 바닥선(인접 프레임): {adj:.2f} dB")
        print(f"        바닥선 대비 차이: {gap:.2f} dB")
        if gap <= 1.5:
            print("        판정: 사실상 동일. 바로 사용 가능")
        elif gap <= 4:
            print("        판정: 거의 안 보임. 사용 권장")
        elif gap <= 7:
            print("        판정: 자세히 보면 보임. 눈으로 확인 필요")
        else:
            print("        판정: 명확히 튐. 이 클립은 루프에 부적합")


def cut(path, out, start, end):
    frames, fps, n = load_small(path)
    subprocess.run(["ffmpeg", "-y", "-i", str(path),
                    "-vf", f"select='between(n\\,{start}\\,{end-1})',setpts=N/FRAME_RATE/TB",
                    "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out), "-loglevel", "error"], check=True)
    print(f"[완료] {start}~{end} ({(end-start)/fps:.2f}초) -> {out}")


def main():
    ap = argparse.ArgumentParser(description="최적 루프 구간 탐색")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="루프 후보 구간 탐색")
    s.add_argument("input")
    s.add_argument("--min-sec", type=float, default=4.0)
    s.add_argument("--top", type=int, default=8)

    c = sub.add_parser("cut", help="구간 잘라내기")
    c.add_argument("input")
    c.add_argument("-o", "--output", required=True)
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)

    a = ap.parse_args()
    if a.cmd == "scan":
        scan(a.input, a.min_sec, a.top)
    else:
        cut(a.input, a.output, a.start, a.end)


if __name__ == "__main__":
    main()
