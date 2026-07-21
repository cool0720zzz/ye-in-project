#!/usr/bin/env python3
"""로파이걸 스타일 'now playing' 오버레이 — 제목 + 진행바 + 시간 카운터.

루프 영상을 곡 길이만큼 반복하면서, 그 위에:
  - 제목/아티스트 텍스트
  - 곡 길이에 맞춰 차오르는 진행바
  - 경과/전체 시간 카운터 (M:SS / M:SS)
를 프레임 정확하게 구워넣는다.

사용법
------
# 곡 오디오까지 얹어 최종본
python overlay_nowplaying.py --video loop.mp4 --audio song.mp3 \
    --title "네온" --artist "예인" -o out.mp4

# 오디오 없이 지정 길이로 프리뷰
python overlay_nowplaying.py --video loop.mp4 --duration 20 \
    --title "네온" --artist "예인" -o preview.mp4

의존성: ffmpeg/ffprobe, Windows 맑은 고딕(malgun.ttf)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1920, 1080
FONT_SRC = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="루프 영상")
    ap.add_argument("--audio", default=None, help="곡 오디오 (길이·사운드)")
    ap.add_argument("--duration", type=float, default=None, help="오디오 없을 때 길이(초)")
    ap.add_argument("--title", default=None, help="제목 (생략 시 오디오 파일명 사용)")
    ap.add_argument("--artist", default="", help="아티스트 (기본: 없음)")
    ap.add_argument("--title-only", action="store_true", help="제목만 (진행바·시간 제거)")
    ap.add_argument("--title-size", type=int, default=64, help="제목 글자 크기")
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args()

    if a.audio:
        dur = audio_duration(a.audio)
    elif a.duration:
        dur = a.duration
    else:
        sys.exit("[에러] --audio 또는 --duration 중 하나는 필요합니다.")

    # 제목: 지정 없으면 오디오 파일명(확장자 제외)에서 자동
    title = a.title or (Path(a.audio).stem if a.audio else None)
    if not title:
        sys.exit("[에러] --title 또는 --audio(파일명) 중 하나는 필요합니다.")

    outp = Path(a.output).resolve()
    work = outp.parent
    # 상대경로로 폰트/텍스트 → 드라이브 콜론 이스케이프 지옥 회피
    font = work / "_np_font.ttf"
    if not font.exists():
        shutil.copy(FONT_SRC, font)
    bold = work / "_np_bold.ttf"
    if not bold.exists():
        shutil.copy(FONT_BOLD, bold)
    title_txt = work / "_np_title.txt"
    time_txt = work / "_np_total.txt"
    title_text = f"{a.artist}  —  {title}" if a.artist else title
    title_txt.write_text(title_text, encoding="utf-8")

    # 레이아웃
    bx = 120
    ts = a.title_size
    title_y = H - ts - 80          # 하단 좌측, 큰 볼드 제목
    title_draw = (
        f"drawtext=fontfile=_np_bold.ttf:textfile=_np_title.txt:"
        f"x={bx}:y={title_y}:fontsize={ts}:fontcolor=white:"
        f"shadowcolor=black@0.65:shadowx=3:shadowy=3"
    )

    if a.title_only:
        # 제목만 (볼드·큰 글자), 진행바·시간 없음
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"{title_draw}")
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(a.video)]
        if a.audio:
            cmd += ["-i", str(a.audio)]
        cmd += ["-t", f"{dur}", "-vf", vf, "-r", "24"]
        if a.audio:
            cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                str(outp), "-loglevel", "error"]
    else:
        # 풀 now-playing: 제목(볼드·큰) + 진행바 + 시간
        by, bw, bh = 980, W - 240, 6
        total_esc = mmss(dur).replace(":", r"\:")
        elapsed = r"%{eif\:floor(t/60)\:d}\:%{eif\:floor(mod(t\,60))\:d\:2}"
        bar_alpha = f"if(lt(X,W*T/{dur}),235,0)"
        fc = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=white@0.18:t=fill,"
            f"{title_draw.replace(f'y={title_y}', f'y={by-ts-24}')},"
            f"drawtext=fontfile=_np_font.ttf:text='{elapsed} / {total_esc}':"
            f"x={bx+bw}-tw:y={by-52}:fontsize=34:fontcolor=white@0.9:"
            f"shadowcolor=black@0.6:shadowx=2:shadowy=2[base];"
            f"color=c=white:s={bw}x{bh}:d={dur+1}:r=24,format=rgba,"
            f"geq=r=255:g=255:b=255:a='{bar_alpha}'[bar];"
            f"[base][bar]overlay={bx}:{by}[out]"
        )
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(a.video)]
        if a.audio:
            cmd += ["-i", str(a.audio)]
        cmd += ["-t", f"{dur}", "-filter_complex", fc, "-map", "[out]", "-r", "24"]
        if a.audio:
            cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                str(outp), "-loglevel", "error"]

    mode = "제목만" if a.title_only else "풀"
    print(f"[정보] {title} / {mmss(dur)} / {int(dur)}초 / {mode}")
    subprocess.run(cmd, check=True, cwd=work)
    for f in (title_txt, time_txt):
        f.unlink(missing_ok=True)
    print(f"[완료] -> {outp}")


if __name__ == "__main__":
    main()
