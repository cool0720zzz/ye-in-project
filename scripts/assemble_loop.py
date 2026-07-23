# -*- coding: utf-8 -*-
"""캐글 청크 릴레이로 회수한 base64 파트 5개를 조립해 loop_best.mp4 복원 + MD5 검증."""
import base64, hashlib, re, sys, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.join(os.path.dirname(__file__), "..", "grok_stills")
EXPECT_LEN = 222708
EXPECT_MD5 = "e625970eb714e513b2dbb40ff8ebb509"

NAMES = ["part1", "part2a", "part2b", "part3", "part4", "part5"]
MARKERS = ("C1E", "C2E", "C3E", "C4E", "C5E", "D1E", "D2E")
parts = []
for name in NAMES:
    p = os.path.join(BASE, f"loop_best.b64.{name}")
    with open(p, "r", encoding="ascii") as f:
        s = re.sub(r"\s", "", f.read())
    # 어제 저장분(part1)은 끝에 마커가 포함돼 있음 → 제거
    if s.endswith(MARKERS):
        s = s[:-3]
    parts.append(s)
    print(f"{name}: {len(s)} chars")

b64 = "".join(parts)
print("total:", len(b64), "(expect", EXPECT_LEN, ")")
if len(b64) != EXPECT_LEN:
    print("!! LENGTH MISMATCH"); sys.exit(1)

data = base64.b64decode(b64)
md5 = hashlib.md5(data).hexdigest()
print("bytes:", len(data), "md5:", md5)
if md5 != EXPECT_MD5:
    print("!! MD5 MISMATCH (expect", EXPECT_MD5, ")"); sys.exit(1)

out = os.path.join(BASE, "A02_워커홀릭_루프.mp4")
with open(out, "wb") as f:
    f.write(data)
print("OK →", out)
