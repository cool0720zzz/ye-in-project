#!/usr/bin/env python3
"""
예인 시티팝 루프 영상 파이프라인
Grok 15초 클립 -> 심리스 루프 -> 곡 길이만큼 확장 + 오디오 합성

의존성: ffmpeg, ffprobe (PATH에 있어야 함)

무페이드 원칙
------------
크로스페이드는 루프 주기마다 미세 깜빡임(피로감)을 만든다. 기본은 항상 무페이드:
  - 대칭 앰비언트 모션(좌우 흔들림/깜빡임/스팀) -> boomerang
  - 자연 루프로 뽑은 클립(터널/연속 광류/흐린 비) -> build 로 바로 하드 루프
  - crossfade 는 최후의 폴백으로만 남겨둠.

사용법
------
# 1) 부메랑 심리스 루프 (정방향+역방향) — 대칭 모션용, 무페이드
python make_loop.py boomerang input.mp4 -o loop_seamless.mp4

# 2) 자연 루프 클립을 곡 길이만큼 반복 + 오디오 합성 -> 최종 영상 (하드 루프, 무페이드)
python make_loop.py build loop_seamless.mp4 song.mp3 -o final.mp4
#    (Grok 자연 루프 클립이면 별도 심리스 처리 없이 바로 이 단계)

# 3) 한 번에: 부메랑 루프 만들고 바로 곡 얹기 (기본 무페이드)
python make_loop.py auto input.mp4 song.mp3 -o final.mp4

# 4) [폴백] 크로스페이드 심리스 루프 — 자연 루프가 안 될 때만
python make_loop.py crossfade input.mp4 -o loop_seamless.mp4 --xfade 0.7
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _check_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"[에러] '{tool}' 를 PATH에서 찾을 수 없습니다. FFmpeg를 설치하세요.")


def _run(cmd):
    print("  $ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def boomerang(inp, outp):
    """정방향 + 역방향 이어붙여 시작/끝 프레임을 자동 일치시킴."""
    _run([
        "ffmpeg", "-y", "-i", str(inp),
        "-filter_complex", "[0:v]reverse[r];[0:v][r]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(outp),
    ])
    print(f"[완료] 부메랑 루프 -> {outp}")


def crossfade(inp, outp, xfade):
    """
    클립 끝 xfade초를 클립 시작으로 디졸브 -> 이음새 은폐.
    출력 길이 = 원본 - xfade. 루프 지점 프레임이 서로 일치.
    """
    d = probe_duration(inp)
    if xfade >= d / 2:
        sys.exit(f"[에러] --xfade({xfade}s)가 너무 큽니다. 클립 길이({d:.2f}s)의 절반 미만이어야 합니다.")
    offset = d - 2 * xfade
    fc = (
        f"[0:v]split[a][b];"
        f"[a]trim=start={xfade},setpts=PTS-STARTPTS[body];"
        f"[b]trim=0:{xfade},setpts=PTS-STARTPTS[head];"
        f"[body][head]xfade=transition=fade:duration={xfade}:offset={offset}[v]"
    )
    _run([
        "ffmpeg", "-y", "-i", str(inp),
        "-filter_complex", fc,
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(outp),
    ])
    print(f"[완료] 크로스페이드 루프({xfade}s) -> {outp}  (길이 {d - xfade:.2f}s)")


def build(loop, audio, outp):
    """심리스 루프를 오디오 길이만큼 무한 반복 + 합성."""
    dur = probe_duration(audio)
    print(f"[정보] 오디오 길이 {dur:.2f}s 만큼 루프 확장")
    _run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(loop),
        "-i", str(audio),
        "-map", "0:v", "-map", "1:a",
        "-shortest",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(outp),
    ])
    print(f"[완료] 최종 영상 -> {outp}")


def main():
    _check_tools()
    p = argparse.ArgumentParser(description="예인 시티팝 루프 영상 파이프라인")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("boomerang", help="부메랑 심리스 루프")
    b.add_argument("input")
    b.add_argument("-o", "--output", required=True)

    c = sub.add_parser("crossfade", help="크로스페이드 심리스 루프")
    c.add_argument("input")
    c.add_argument("-o", "--output", required=True)
    c.add_argument("--xfade", type=float, default=0.7, help="디졸브 초 (기본 0.7)")

    bd = sub.add_parser("build", help="루프 확장 + 오디오 합성")
    bd.add_argument("loop")
    bd.add_argument("audio")
    bd.add_argument("-o", "--output", required=True)

    a = sub.add_parser("auto", help="루프 생성 + 오디오 합성 한 번에 (기본 무페이드)")
    a.add_argument("input")
    a.add_argument("audio")
    a.add_argument("-o", "--output", required=True)
    a.add_argument("--mode", choices=["boomerang", "crossfade"], default="boomerang",
                   help="기본 boomerang(무페이드). crossfade는 폴백")
    a.add_argument("--xfade", type=float, default=0.7)

    args = p.parse_args()

    if args.cmd == "boomerang":
        boomerang(args.input, args.output)
    elif args.cmd == "crossfade":
        crossfade(args.input, args.output, args.xfade)
    elif args.cmd == "build":
        build(args.loop, args.audio, args.output)
    elif args.cmd == "auto":
        tmp = Path(args.output).with_suffix(".loop.mp4")
        if args.mode == "boomerang":
            boomerang(args.input, tmp)
        else:
            crossfade(args.input, tmp, args.xfade)
        build(tmp, args.audio, args.output)
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
