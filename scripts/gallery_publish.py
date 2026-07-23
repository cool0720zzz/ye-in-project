#!/usr/bin/env python3
"""결과물(이미지·루프·리릭비디오)을 폰 갤러리에 올린다.

갤러리는 ye-in-editor 저장소(GitHub Pages)의 gallery.html 이 열고,
이 스크립트가 갱신하는 gallery/manifest.json 을 GitHub API로 읽어 카드로 띄운다.
썸네일은 base64로 manifest 안에 인라인 (비공개 repo라 raw 접근이 안 되므로).

  이미지   → 다운스케일 JPEG
  루프     → 짧은 GIF (움직임을 봐야 이음새를 판단하므로)
  리릭비디오 → 포스터 프레임 1장

사용:
  python gallery_publish.py --file lyric_output/네온.mp4 --type video \
      --id neon-lyricvideo --title "네온 리릭비디오" \
      --verdict "36줄 LRC 싱크 · 3:50 · 아웃트로 최신판"

그 뒤 gallery/manifest.json 을 커밋·푸시하면 폰에서 바로 뜬다.
"""
import argparse
import base64
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "gallery" / "manifest.json"
KST = timezone(timedelta(hours=9))
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True)


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def make_thumb(src, kind, work):
    """카드 썸네일을 만들어 data URI로 반환."""
    src = str(Path(src).resolve())
    if kind == "loop":
        # 짧은 gif — 이음새·움직임을 눈으로 판단
        out = work / "_thumb.gif"
        run(["ffmpeg", "-y", "-t", "3", "-i", src,
             "-vf", "fps=10,scale=360:-2:flags=lanczos", str(out), "-loglevel", "error"])
        return data_uri(out, "image/gif")
    if kind in ("video", "lyricvideo"):
        # 곡 중간 지점 포스터 1장
        dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=nw=1:nk=1", src]).stdout.decode().strip() or 0)
        out = work / "_thumb.jpg"
        run(["ffmpeg", "-y", "-ss", f"{dur*0.5:.1f}", "-i", src, "-frames:v", "1",
             "-vf", "scale=760:-2", "-q:v", "4", str(out), "-loglevel", "error"])
        return data_uri(out, "image/jpeg")
    # image
    out = work / "_thumb.jpg"
    run(["ffmpeg", "-y", "-i", src, "-vf", "scale='min(760,iw)':-2",
         "-q:v", "4", str(out), "-loglevel", "error"])
    return data_uri(out, "image/jpeg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="결과물 경로")
    ap.add_argument("--type", required=True, choices=["image", "loop", "video", "lyricvideo"])
    ap.add_argument("--id", required=True, help="고유 id (재발행 시 같은 id면 교체)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--verdict", default="", help="클로드 자동 판정 한 줄")
    ap.add_argument("--meta", default=None, help="표시용 경로 (기본: --file)")
    ap.add_argument("--final", action="store_true",
                    help="완성 결과물 — 뒤에 이어갈 게 없음. 폰에서 '이어가기' 대신 '완료' 버튼")
    a = ap.parse_args()

    src = Path(a.file)
    if not src.exists():
        sys.exit(f"[에러] 파일 없음: {src}")

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    work = MANIFEST.parent
    thumb = make_thumb(src, a.type, work)
    for f in ("_thumb.jpg", "_thumb.gif"):
        (work / f).unlink(missing_ok=True)

    data = {"updated": "", "items": []}
    if MANIFEST.exists():
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    rel = a.meta or str(src).replace(str(ROOT) + "\\", "").replace(str(ROOT) + "/", "")
    item = {
        "id": a.id, "type": a.type, "title": a.title,
        "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "verdict": a.verdict, "meta": rel, "status": "new",
        "final": bool(a.final), "thumb": thumb,
    }
    items = [it for it in data.get("items", []) if it.get("id") != a.id]
    items.insert(0, item)                     # 새 것이 위로
    data["items"] = items
    data["updated"] = datetime.now(KST).isoformat()

    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    size_kb = len(MANIFEST.read_bytes()) / 1024
    print(f"[발행] {a.title} ({a.type}) · 썸 {len(thumb)//1024}KB · manifest {size_kb:.0f}KB · 총 {len(items)}개")
    if size_kb > 900:
        print("  ⚠️ manifest가 900KB를 넘음 — GitHub API content 한도(1MB) 근접. 오래된 항목 정리 필요")


if __name__ == "__main__":
    main()
