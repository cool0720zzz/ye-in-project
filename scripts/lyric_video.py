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
F_REG, F_BOLD = ".lv_cache/_lv_font.ttf", ".lv_cache/_lv_bold.ttf"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

# 레이아웃
CARD_W, CARD_H = 720, 720  # 왼쪽 이미지 카드 (--card 로 변경. 16:9 소스면 800x450 권장)
CARD_X = 130
LYR_GAP = 100              # 카드 오른쪽 끝 ~ 가사 시작 사이 여백
LYR_STEP = 82              # 줄 간격
# (앞뒤 오프셋, 글자크기, 불투명도) — 현재 줄(0)은 검은 박스로 강조,
# 아래로 갈수록 흐려지며 사라진다
SLOTS = [(-1, 42, 0.40), (0, 52, 1.00), (1, 44, 0.80), (2, 42, 0.60), (3, 40, 0.35)]
BAR_H = 6                  # 진행바 두께 (폭은 카드 폭에 맞춰 자동)
WAVE_H = 64                # --wave 파형 높이
FPS = 24


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


def beat_commands(audio, dur, fps, base_sigma, peak_sigma, base_bri, peak_bri):
    """비트에 맞춰 배경 보케가 부풀었다 사그라드는 sendcmd 스크립트를 만든다.

    멀리 있는 네온이 박자마다 초점이 나가며 번지는 느낌 — 배경에만 걸고
    인물 카드는 선명하게 남긴다.

    ⚠️ 실측으로 확인한 두 가지 (scratchpad/verify.py):
      1. gblur와 eq에 **같은 인스턴스 이름**을 주면 sendcmd가 엉뚱하게 먹어
         밝기가 오히려 반대로 간다. 반드시 @blr / @brt 로 분리할 것.
      2. sendcmd는 약 2프레임 늦게 적용된다. 그만큼 앞당겨 발행해야
         비트와 위상이 맞는다. (보정 전 상관 +0.40 → 보정 후 +0.89)
    """
    import librosa                      # --beat 쓸 때만 필요
    import numpy as np

    y, sr = librosa.load(audio, sr=22050, mono=True)
    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    et = librosa.frames_to_time(np.arange(len(env)), sr=sr, hop_length=512)
    amp = np.interp(beats, et, env)
    amp = amp / (amp.max() or 1.0)      # 세게 친 박자일수록 크게 번진다

    t = np.arange(int(dur * fps)) / fps
    pulse = np.zeros_like(t)
    for bt, a in zip(beats, amp):
        m = (t >= bt) & (t - bt < 0.5)
        pulse[m] = np.maximum(pulse[m], a * np.exp(-(t[m] - bt) / 0.16))

    lead = 2 / fps
    out = []
    for tt, p in zip(t, pulse):
        ts = max(0.0, tt - lead)
        out.append(f"{ts:.3f} gblur@blr sigma "
                   f"{base_sigma + (peak_sigma - base_sigma) * p:.2f};")
        out.append(f"{ts:.3f} eq@brt brightness "
                   f"{base_bri + (peak_bri - base_bri) * p:.3f};")
    return "\n".join(out), len(beats)


def esc(path_or_text):
    """drawtext 옵션 값 안의 콜론·작은따옴표 이스케이프."""
    return str(path_or_text).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="곡 오디오")
    ap.add_argument("--lyrics", default=None, help="가사 .md (lyrics/A01_네온.md)")
    ap.add_argument("--bg", required=True,
                    help="배경 (흐리게 깔린다). 이미지·영상 둘 다 가능")
    ap.add_argument("--card-src", default=None,
                    help="카드에 넣을 소스. 생략하면 --bg 를 같이 쓴다. "
                         "배경은 사진, 카드는 루프 영상 같은 조합에 쓴다")
    ap.add_argument("--timed", default=None,
                    help="⭐ LRC/SRT 파일 — 있으면 --lyrics·--cues 불필요 (가장 정확)")
    ap.add_argument("--cues", default=None, help="섹션 타임코드 파일 (없으면 균등 분배)")
    ap.add_argument("--lyrics-x", type=int, default=None,
                    help="가사 시작 x (기본: 카드 오른쪽에 자동 배치)")
    ap.add_argument("--card", default=f"{CARD_W}x{CARD_H}",
                    help="왼쪽 카드 크기 WxH (기본 720x720). "
                         "16:9 소스는 800x450 이 잘리는 데 없이 예쁘다")
    ap.add_argument("--title", default=None, help="제목 (생략 시 오디오 파일명)")
    ap.add_argument("--artist", default="", help="아티스트 (기본: 표기 안 함)")
    ap.add_argument("--no-bar", action="store_true", help="진행바·시간 빼고 제목만")
    ap.add_argument("--wave", action="store_true",
                    help="⭐ 밋밋한 진행바 대신 곡 전체 파형. 재생된 만큼만 밝아진다 "
                         "(움직이지 않아 가사를 방해하지 않는다)")
    ap.add_argument("--beat", action="store_true",
                    help="⭐ 비트에 맞춰 배경 네온이 초점 나가며 번지는 효과 (librosa 필요)")
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

    m = re.fullmatch(r"(\d+)\s*[xX*]\s*(\d+)", a.card.strip())
    if not m:
        sys.exit(f"[에러] --card 는 '800x450' 형식이어야 합니다: {a.card!r}")
    cw, ch = int(m.group(1)), int(m.group(2))
    # 가사는 카드 오른쪽에 붙여 배치 — 카드를 줄여도 두 단 간격이 유지된다
    lyr_x = a.lyrics_x if a.lyrics_x else CARD_X + cw + LYR_GAP
    if lyr_x + 760 > W:
        sys.exit(f"[에러] 가사 시작 x={lyr_x} 이 너무 오른쪽이라 긴 줄이 잘립니다. "
                 f"카드를 좁히거나 --lyrics-x 로 당기세요.")
    # ── 왼쪽 세로 블록: [카드] → [제목] → [진행바] 를 하나로 묶어 화면 수직 중앙에.
    #    진행바 폭을 카드 폭에 맞춰야 오른쪽 가사와 레이아웃이 맞아 보인다.
    TITLE_SIZE, GAP_CT, GAP_TB = 52, 34, 26
    bar_h = WAVE_H if a.wave else BAR_H
    block_h = ch + GAP_CT + TITLE_SIZE + (0 if a.no_bar else GAP_TB + bar_h)
    cy = max(0, (H - block_h) // 2)
    title_y = cy + ch + GAP_CT
    bar_y = title_y + TITLE_SIZE + GAP_TB
    # 가사 스택(-1~+3행)의 중심을 왼쪽 블록의 중심과 맞춘다
    lyr_y = cy + block_h // 2 - LYR_STEP

    dur = audio_duration(a.audio)
    title = a.title or Path(a.audio).stem
    if a.timed:
        timeline, cues = parse_timed(a.timed), None
    else:
        cues = parse_cues(a.cues) if a.cues else None
        timeline = build_timeline(sections, cues, dur)

    # drawtext의 enable 판정이 실측상 1프레임 늦게 걸린다 (프레임 정밀 측정으로 확인:
    # 이론상 1075프레임에서 바뀌어야 할 줄이 1076에서 바뀜). 그만큼 앞당겨 보정.
    lead = 1 / FPS
    timeline = [(max(0.0, s - lead), max(0.0, e - lead), t) for s, e, t in timeline]

    outp = Path(a.output).resolve()
    work = outp.parent
    work.mkdir(parents=True, exist_ok=True)
    # 폰트는 상대경로로 넘겨야 드라이브 콜론 이스케이프를 피할 수 있다.
    # 결과물 폴더가 지저분해지지 않도록 숨김 캐시 폴더에 둔다.
    cache = work / ".lv_cache"
    cache.mkdir(exist_ok=True)
    for src, dst in ((FONT_SRC, F_REG), (FONT_BOLD, F_BOLD)):
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
                f"drawtext=fontfile={F_BOLD if cur else F_REG}:"
                f"textfile=_lv_{j:03d}.txt:"
                f"x={lyr_x}:y={lyr_y + off * LYR_STEP}:"
                f"fontsize={size}:fontcolor=white@{alpha}:{style}:"
                f"enable='between(t,{s:.3f},{e:.3f})'"
            )

    total_esc = mmss(dur).replace(":", r"\:")
    elapsed = r"%{eif\:floor(t/60)\:d}\:%{eif\:floor(mod(t\,60))\:d\:2}"

    # ── 배경 처리: 비트 반응이면 sendcmd로 blur·밝기를 프레임마다 흔든다
    n_beats = 0
    if a.beat:
        script, n_beats = beat_commands(a.audio, dur, FPS,
                                        base_sigma=16, peak_sigma=32,
                                        base_bri=-0.32, peak_bri=-0.14)
        (work / "_lv_cmd.txt").write_text(script, encoding="utf-8")
        tmp.append(work / "_lv_cmd.txt")
        bg_fx = ("sendcmd=f=_lv_cmd.txt,gblur@blr=sigma=16,"
                 "eq@brt=brightness=-0.32:saturation=0.85")
    else:
        bg_fx = "boxblur=24:2,eq=brightness=-0.28:saturation=0.85"

    # ── 왼쪽 블록: 카드 아래 제목, 그 아래 카드 폭에 맞춘 진행바
    left = (f"drawtext=fontfile={F_BOLD}:textfile=_lv_title.txt:"
            f"x={CARD_X}:y={title_y}:fontsize={TITLE_SIZE}:fontcolor=white:"
            f"shadowcolor=black@0.65:shadowx=3:shadowy=3")
    if not a.no_bar:
        left = (f"drawbox=x={CARD_X}:y={bar_y}:w={cw}:h={BAR_H}:"
                f"color=white@0.18:t=fill," + left +
                f",drawtext=fontfile={F_REG}:text='{elapsed} / {total_esc}':"
                f"x={CARD_X + cw}-tw:y={title_y + 20}:fontsize=30:fontcolor=white@0.85:"
                f"shadowcolor=black@0.6:shadowx=2:shadowy=2")

    # ── 입력 구성. 배경과 카드를 다른 소스로 줄 수 있다
    #    (배경=사진 흐리게 / 카드=루프 영상 같은 조합)
    ins = []

    def add_visual(path):
        p = str(Path(path).resolve())
        ins.append(["-stream_loop", "-1", "-i", p]
                   if Path(path).suffix.lower() in VIDEO_EXT
                   else ["-loop", "1", "-i", p])
        return len(ins) - 1

    i_bg = add_visual(a.bg)
    i_card = add_visual(a.card_src) if a.card_src else None
    ins.append(["-i", str(Path(a.audio).resolve())])
    i_aud = len(ins) - 1

    i_wave = None
    if a.wave and not a.no_bar:
        wave_png = work / "_lv_wave.png"
        run(["ffmpeg", "-y", "-i", str(Path(a.audio).resolve()),
             "-filter_complex",
             # ⚠️ scale=cbrt 필수. 기본값(lin)은 이 장르의 좁은 다이내믹 레인지에서
             #    띠의 10.9%밖에 못 채워 긁힌 자국처럼 보인다 (cbrt는 46.9%)
             f"showwavespic=s={cw}x{WAVE_H}:colors=white:"
             f"split_channels=0:scale=cbrt",
             "-frames:v", "1", str(wave_png), "-loglevel", "error"])
        tmp.append(wave_png)
        ins.append(["-loop", "1", "-i", str(wave_png)])
        i_wave = len(ins) - 1

    if i_card is None:                       # 한 소스를 배경·카드에 같이 쓴다
        head = f"[{i_bg}:v]split=2[b0][b1];"
        bg_in, card_in = "[b0]", "[b1]"
    else:
        head = ""
        bg_in, card_in = f"[{i_bg}:v]", f"[{i_card}:v]"

    fc = (
        head +
        # 배경: 꽉 채워 블러 + 어둡게 (먼 거리 네온이 뭉개지는 층)
        f"{bg_in}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"{bg_fx}[bg];"
        # 카드: 인물. 배경 효과가 걸리지 않아 선명하게 남는다
        f"{card_in}scale={cw}:{ch}:force_original_aspect_ratio=increase,"
        f"crop={cw}:{ch}[card];"
        f"[bg][card]overlay={CARD_X}:{cy}[base];"
        f"[base]{left}," + ",".join(draws) + "[body];"
    )
    if a.no_bar:
        fc = fc[:-len("[body];")] + "[out]"
    elif i_wave is not None:
        # 곡 전체 파형을 깔고(어둡게), 재생된 구간만 밝은 판으로 덮는다.
        # lumakey가 showwavespic의 검은 배경을 투명으로 바꿔 준다.
        played = f"lt(X,W*T/{dur})"
        fc += (
            f"[{i_wave}:v]format=rgba,split=2[wA][wB];"
            f"[wA]lumakey=threshold=0.06:tolerance=0.06,"
            f"colorchannelmixer=aa=0.30[wdim];"
            f"[wB]geq=r='if({played},r(X,Y),0)':g='if({played},g(X,Y),0)':"
            f"b='if({played},b(X,Y),0)':a=255,"
            f"lumakey=threshold=0.06:tolerance=0.06[wbr];"
            f"[body][wdim]overlay={CARD_X}:{bar_y}[bw];"
            f"[bw][wbr]overlay={CARD_X}:{bar_y}[out]"
        )
    else:
        fc += (f"color=c=white:s={cw}x{BAR_H}:d={dur + 1}:r={FPS},format=rgba,"
               f"geq=r=255:g=255:b=255:a='if(lt(X,W*T/{dur}),235,0)'[bar];"
               f"[body][bar]overlay={CARD_X}:{bar_y}[out]")

    # 가사가 많으면 필터가 수만 자가 되어 Windows 명령줄 한도(~32KB)를 넘는다
    # → 파일로 넘긴다
    fc_file = work / "_lv_filter.txt"
    fc_file.write_text(fc, encoding="utf-8")
    tmp.append(fc_file)

    cmd = ["ffmpeg", "-y"]
    for chunk in ins:
        cmd += chunk
    cmd += ["-t", f"{dur}", "-filter_complex_script", "_lv_filter.txt",
            "-map", "[out]", "-map", f"{i_aud}:a", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            str(outp), "-loglevel", "error"]

    kind = lambda p: "영상" if Path(p).suffix.lower() in VIDEO_EXT else "스틸"
    src = (f"배경={kind(a.bg)}·카드={kind(a.card_src)}" if a.card_src
           else f"배경·카드={kind(a.bg)}")
    if a.wave and not a.no_bar:
        src += " / 파형바"
    mode = (f"⭐ {Path(a.timed).name}" if a.timed
            else f"큐 {Path(a.cues).name}" if cues else "⚠️ 균등 분배(미리보기)")
    fx = f" / 비트반응 {n_beats}비트" if a.beat else ""
    print(f"[정보] {title} / {mmss(dur)} / 가사 {len(timeline)}줄 / {src} / "
          f"타이밍: {mode}{fx}")
    try:
        subprocess.run(cmd, check=True, cwd=work)
    finally:
        for f in tmp:
            f.unlink(missing_ok=True)
    print(f"[완료] -> {outp}")


if __name__ == "__main__":
    main()
