#!/usr/bin/env python3
"""리릭비디오 — 메인 이미지 + 옆에 흐르는 가사 + 하단 진행바.

뮤직비디오(립싱크·컷 편집)보다 훨씬 싸게, 이 프로젝트의 강점인 **가사**를
정면으로 보여주는 포맷. 배경은 스틸 이미지든 루프 영상이든 둘 다 된다.

    ┌──────────────────────────────────┐
    │  ┌────────┐                      │
    │  │        │   지난 줄 (흐리게)     │
    │  │  예인   │   현재 줄 (밝게)  ←   │
    │  │        │   다음 줄 (흐리게)     │
    │  └────────┘                      │
    │  예인 — 네온                      │
    │  ▬▬▬▬▬▬▬▬▬───────────  1:24/3:47 │
    └──────────────────────────────────┘

타이밍을 어디서 얻는가 — 좋은 순서대로
--------------------------------------
가사 **텍스트**는 이미 `lyrics/*.md`에 있다. 없는 건 **어느 줄이 몇 초에 나오는가**뿐이다.

  1. ⭐ **LRC/SRT 파일** (`--timed`) — 제일 정확하고 손이 안 간다.
     Suno가 주면 그걸 쓰고, 안 주면 무료 온라인 LRC 메이커로 만들면 된다.
     이게 있으면 `--lyrics`도 `--cues`도 필요 없다.
  2. **섹션 큐** (`--cues`) — 곡 들으면서 섹션 시작 시각만 10개쯤 받아적는다(곡당 5분).
     섹션 안에서는 자동 균등 분배. 실용적으로 충분히 잘 붙는다.
  3. 아무것도 없음 — 전체 줄을 곡 길이에 균등 분배. **미리보기 전용.**

사용법
------
# 1) ⭐ LRC/SRT가 있으면 이것만으로 끝
python lyric_video.py --audio 네온.mp3 --timed 네온.lrc \
    --bg 예인.png --title 네온 --artist 예인 -o 네온_리릭.mp4

# 2) 섹션 큐로 (큐 파일 틀은 --dump-cues 로 뽑는다)
python lyric_video.py --lyrics ../lyrics/A01_네온.md --audio x --bg x --dump-cues > 네온.cue
python lyric_video.py --audio 네온.mp3 --lyrics ../lyrics/A01_네온.md \
    --bg 예인.png --title 네온 --artist 예인 --cues 네온.cue -o 네온_리릭.mp4

# 3) 대충 미리보기
python lyric_video.py --audio 네온.mp3 --lyrics ../lyrics/A01_네온.md \
    --bg 예인.png --title 네온 --artist 예인 -o 미리보기.mp4

큐 파일 형식 (`--cues`)
----------------------
곡을 한 번 들으면서 **섹션이 시작하는 시각**만 받아적는다. 순서는 가사와 같아야 한다.
줄 안에서는 자동으로 균등 분배되므로 섹션 경계만 맞으면 충분히 잘 붙는다.

    0:00  Intro
    0:11  Verse 1
    0:34  Pre-Chorus
    0:45  Chorus
    1:08  Verse 2
    ...
    3:20  Outro
    3:47  END        ← 마지막 섹션이 끝나는 시각. 없으면 곡 끝까지로 본다

`#`으로 시작하는 줄과 빈 줄은 무시. 섹션 이름은 참고용이라 대소문자·표기 자유.

의존성: ffmpeg/ffprobe, Windows 맑은 고딕(malgun.ttf)
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1920, 1080
FONT_SRC = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

# 레이아웃
CARD = 720                 # 왼쪽 이미지 카드 한 변
CARD_X, CARD_Y = 130, 150
LYR_X = 980                # 가사 시작 x
LYR_Y = 470                # 현재 줄의 y (여기를 중심으로 위아래 배치)
LYR_STEP = 82              # 줄 간격
# (앞뒤 오프셋, 글자크기, 불투명도) — 현재 줄(0)은 검은 박스로 강조,
# 아래로 갈수록 흐려지며 사라진다
SLOTS = [(-1, 42, 0.40), (0, 52, 1.00), (1, 44, 0.80), (2, 42, 0.60), (3, 40, 0.35)]
BAR_X, BAR_Y, BAR_H = 130, 980, 6


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def audio_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.stdout.strip())


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def parse_time(s):
    """'1:23.5' / '83.5' / '1:02:03' 모두 초로."""
    parts = s.strip().split(":")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def parse_lyrics(md_path):
    """가사 .md에서 `## 가사` 아래 첫 코드펜스를 뽑아 섹션 리스트로.

    반환: [(섹션명, [가사줄...]), ...]  — 빈 줄은 버린다(연 구분은 타이밍에 영향 없음).
    """
    text = Path(md_path).read_text(encoding="utf-8")
    m = re.search(r"^##\s*가사\s*$(.*?)^```\s*$(.*?)^```\s*$",
                  text, re.M | re.S)
    if not m:
        # `## 가사` 헤더가 없는 파일도 허용 — 첫 코드펜스를 그냥 쓴다
        m = re.search(r"^```\s*$(.*?)^```\s*$", text, re.M | re.S)
        if not m:
            sys.exit(f"[에러] {md_path} 에서 가사 코드블록을 찾지 못했습니다.")
        body = m.group(1)
    else:
        body = m.group(2)

    sections, name, lines = [], None, []
    for raw in body.splitlines():
        ln = raw.strip()
        tag = re.fullmatch(r"\[(.+?)\]", ln)
        if tag:
            if name is not None:
                sections.append((name, lines))
            name, lines = tag.group(1), []
        elif ln:
            lines.append(ln)
    if name is not None:
        sections.append((name, lines))
    if not sections:
        sys.exit(f"[에러] {md_path} 에 [Verse 1] 같은 섹션 태그가 없습니다.")
    return sections


def parse_timed(path):
    """LRC / SRT → [(시작, 끝, 가사줄), ...]

    Suno·유튜브 자막·온라인 LRC 메이커 등 **타임코드가 이미 박힌** 파일을 그대로 쓴다.
    이게 있으면 --lyrics 도 --cues 도 필요 없다.
    """
    text = Path(path).read_text(encoding="utf-8-sig")

    # ── SRT: "00:00:12,340 --> 00:00:15,000"
    srt = re.findall(
        r"([\d:,.]+)\s*-->\s*([\d:,.]+)\s*\n(.*?)(?=\n\s*\n|\Z)",
        text, re.S)
    if srt:
        out = []
        for s, e, body in srt:
            line = " ".join(l.strip() for l in body.splitlines() if l.strip())
            if line:
                out.append((parse_time(s.replace(",", ".")),
                            parse_time(e.replace(",", ".")), line))
        if out:
            return sorted(out)

    # ── LRC: "[00:12.34]가사"  (한 줄에 타임스탬프 여러 개 가능)
    marks = []
    for raw in text.splitlines():
        stamps = re.findall(r"\[(\d+:\d+(?:[.:]\d+)?)\]", raw)
        if not stamps:
            continue                       # [ar:], [ti:] 같은 메타태그는 건너뜀
        line = re.sub(r"\[[^\]]*\]", "", raw).strip()
        for st in stamps:
            marks.append((parse_time(st), line))
    if marks:
        marks.sort()
        out = []
        for i, (s, line) in enumerate(marks):
            e = marks[i + 1][0] if i + 1 < len(marks) else s + 4.0
            if line:                       # 빈 줄은 앞 줄의 끝 시각 역할만 하고 표시 안 함
                out.append((s, e, line))
        if out:
            return out

    sys.exit(f"[에러] {path} 를 LRC로도 SRT로도 읽지 못했습니다.")


def parse_cues(path):
    """큐 파일 → [(초, 이름), ...]"""
    cues = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"([\d:.]+)\s+(.*)", ln)
        if not m:
            sys.exit(f"[에러] 큐 파일 해석 실패: {raw!r}\n     '0:45  Chorus' 형식이어야 합니다.")
        cues.append((parse_time(m.group(1)), m.group(2).strip()))
    if not cues:
        sys.exit("[에러] 큐 파일이 비어 있습니다.")
    return cues


def build_timeline(sections, cues, dur):
    """(시작, 끝, 가사줄) 리스트로 평탄화."""
    if cues:
        # END 표식은 마지막 경계로만 쓰고 섹션에서는 뺀다
        end_marks = [t for t, n in cues if n.upper() == "END"]
        starts = [(t, n) for t, n in cues if n.upper() != "END"]
        tail = end_marks[0] if end_marks else dur

        if len(starts) != len(sections):
            names = " / ".join(n for _, n in starts)
            secs = " / ".join(n for n, _ in sections)
            sys.exit(f"[에러] 큐 {len(starts)}개 ≠ 가사 섹션 {len(sections)}개\n"
                     f"     큐  : {names}\n"
                     f"     가사: {secs}")
        bounds = [t for t, _ in starts] + [tail]
    else:
        # 큐 없음 — 전체 줄 수로 균등 분배 (미리보기용)
        total = sum(len(l) for _, l in sections) or 1
        bounds, acc = [], 0.0
        for _, lines in sections:
            bounds.append(acc)
            acc += dur * len(lines) / total
        bounds.append(dur)

    timeline = []
    for i, (_, lines) in enumerate(sections):
        s, e = bounds[i], bounds[i + 1]
        if not lines or e <= s:
            continue
        step = (e - s) / len(lines)
        for k, line in enumerate(lines):
            timeline.append((s + k * step, s + (k + 1) * step, line))
    return timeline


def esc(path_or_text):
    """drawtext 옵션 값 안의 콜론·작은따옴표 이스케이프."""
    return str(path_or_text).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="곡 오디오")
    ap.add_argument("--lyrics", default=None, help="가사 .md (lyrics/A01_네온.md)")
    ap.add_argument("--bg", required=True, help="메인 이미지 또는 루프 영상")
    ap.add_argument("--timed", default=None,
                    help="⭐ LRC/SRT 파일 — 있으면 --lyrics·--cues 불필요 (가장 정확)")
    ap.add_argument("--cues", default=None, help="섹션 타임코드 파일 (없으면 균등 분배)")
    ap.add_argument("--title", default=None, help="제목 (생략 시 오디오 파일명)")
    ap.add_argument("--artist", default="", help="아티스트")
    ap.add_argument("--dump-cues", action="store_true",
                    help="가사 섹션 목록을 큐 파일 틀로 출력하고 종료")
    ap.add_argument("-o", "--output", default=None)
    a = ap.parse_args()

    if not a.timed and not a.lyrics:
        sys.exit("[에러] --timed(LRC/SRT) 또는 --lyrics 중 하나는 필요합니다.")

    sections = parse_lyrics(a.lyrics) if a.lyrics else None

    if a.dump_cues:
        if not sections:
            sys.exit("[에러] --dump-cues 에는 --lyrics 가 필요합니다.")
        print("# 곡을 들으면서 각 섹션이 시작하는 시각을 채우세요")
        for name, lines in sections:
            print(f"0:00  {name}".ljust(24) + f"# {len(lines)}줄")
        print("0:00  END".ljust(24) + "# 곡이 끝나는 시각")
        return

    if not a.output:
        sys.exit("[에러] -o/--output 이 필요합니다.")

    dur = audio_duration(a.audio)
    title = a.title or Path(a.audio).stem
    if a.timed:
        timeline, cues = parse_timed(a.timed), None
    else:
        cues = parse_cues(a.cues) if a.cues else None
        timeline = build_timeline(sections, cues, dur)

    outp = Path(a.output).resolve()
    work = outp.parent
    work.mkdir(parents=True, exist_ok=True)
    for src, dst in ((FONT_SRC, "_lv_font.ttf"), (FONT_BOLD, "_lv_bold.ttf")):
        if not (work / dst).exists():
            shutil.copy(src, work / dst)

    # 가사는 줄마다 파일로 — 셸/필터 이스케이프 지옥 회피
    tmp = []
    for i, (_, _, line) in enumerate(timeline):
        f = work / f"_lv_{i:03d}.txt"
        f.write_text(line, encoding="utf-8")
        tmp.append(f)
    title_txt = work / "_lv_title.txt"
    title_txt.write_text(f"{a.artist}  —  {title}" if a.artist else title,
                         encoding="utf-8")
    tmp.append(title_txt)

    # ── 가사 drawtext: 현재 줄은 검은 박스로 강조, 아래로 갈수록 흐려짐
    draws = []
    for i, (s, e, _) in enumerate(timeline):
        for off, size, alpha in SLOTS:
            j = i + off              # 이 슬롯에 그릴 가사 줄
            if not 0 <= j < len(timeline):
                continue
            cur = off == 0
            style = ("box=1:boxcolor=black@0.82:boxborderw=18" if cur
                     else "shadowcolor=black@0.7:shadowx=2:shadowy=2")
            draws.append(
                f"drawtext=fontfile={'_lv_bold.ttf' if cur else '_lv_font.ttf'}:"
                f"textfile=_lv_{j:03d}.txt:"
                f"x={LYR_X}:y={LYR_Y + off * LYR_STEP}:"
                f"fontsize={size}:fontcolor=white@{alpha}:{style}:"
                f"enable='between(t,{s:.3f},{e:.3f})'"
            )

    bw = W - BAR_X * 2
    total_esc = mmss(dur).replace(":", r"\:")
    elapsed = r"%{eif\:floor(t/60)\:d}\:%{eif\:floor(mod(t\,60))\:d\:2}"

    fc = (
        f"[0:v]split=2[b0][b1];"
        # 배경: 꽉 채워 블러 + 어둡게
        f"[b0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=24:2,eq=brightness=-0.28:saturation=0.85[bg];"
        # 카드: 왼쪽 정사각 썸네일
        f"[b1]scale={CARD}:{CARD}:force_original_aspect_ratio=increase,"
        f"crop={CARD}:{CARD}[card];"
        f"[bg][card]overlay={CARD_X}:{CARD_Y}[base];"
        # 하단 제목 + 진행바 틀 + 시간
        f"[base]drawbox=x={BAR_X}:y={BAR_Y}:w={bw}:h={BAR_H}:color=white@0.18:t=fill,"
        f"drawtext=fontfile=_lv_bold.ttf:textfile=_lv_title.txt:"
        f"x={BAR_X}:y={BAR_Y - 88}:fontsize=52:fontcolor=white:"
        f"shadowcolor=black@0.65:shadowx=3:shadowy=3,"
        f"drawtext=fontfile=_lv_font.ttf:text='{elapsed} / {total_esc}':"
        f"x={BAR_X + bw}-tw:y={BAR_Y - 52}:fontsize=32:fontcolor=white@0.9:"
        f"shadowcolor=black@0.6:shadowx=2:shadowy=2,"
        + ",".join(draws) + "[body];"
        # 차오르는 진행바
        f"color=c=white:s={bw}x{BAR_H}:d={dur + 1}:r=24,format=rgba,"
        f"geq=r=255:g=255:b=255:a='if(lt(X,W*T/{dur}),235,0)'[bar];"
        f"[body][bar]overlay={BAR_X}:{BAR_Y}[out]"
    )

    # 가사가 많으면 필터가 수만 자가 되어 Windows 명령줄 한도(~32KB)를 넘는다
    # → 파일로 넘긴다
    fc_file = work / "_lv_filter.txt"
    fc_file.write_text(fc, encoding="utf-8")
    tmp.append(fc_file)

    is_video = Path(a.bg).suffix.lower() in VIDEO_EXT
    cmd = ["ffmpeg", "-y"]
    cmd += ["-stream_loop", "-1", "-i", str(Path(a.bg).resolve())] if is_video \
        else ["-loop", "1", "-i", str(Path(a.bg).resolve())]
    cmd += ["-i", str(Path(a.audio).resolve()),
            "-t", f"{dur}", "-filter_complex_script", "_lv_filter.txt",
            "-map", "[out]", "-map", "1:a", "-r", "24",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            str(outp), "-loglevel", "error"]

    src = "루프영상" if is_video else "스틸"
    mode = (f"⭐ {Path(a.timed).name}" if a.timed
            else f"큐 {Path(a.cues).name}" if cues else "⚠️ 균등 분배(미리보기)")
    print(f"[정보] {title} / {mmss(dur)} / 가사 {len(timeline)}줄 / {src} / 타이밍: {mode}")
    try:
        subprocess.run(cmd, check=True, cwd=work)
    finally:
        for f in tmp:
            f.unlink(missing_ok=True)
    print(f"[완료] -> {outp}")


if __name__ == "__main__":
    main()
