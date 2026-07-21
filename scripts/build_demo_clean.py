"""
예인 인트로 데모 - 자막 없이 순수 영상 효과만
Ken Burns + Crossfade + Breathing + Cafe Color Grade
"""
import cv2
import numpy as np
import math
import os
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSES = os.path.join(BASE, 'video', 'poses')
OUTPUT = os.path.join(BASE, 'video', 'output')
os.makedirs(OUTPUT, exist_ok=True)

W, H = 1280, 720
FPS = 24

def load_img(path):
    img = cv2.imread(path)
    h, w = img.shape[:2]
    scale = max(W/w, H/h) * 1.3
    img = cv2.resize(img, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
    return img

def get_frame(img, zoom, pan_x, pan_y):
    ih, iw = img.shape[:2]
    cw, ch = int(W/zoom), int(H/zoom)
    cx = int(pan_x * max(0, iw - cw))
    cy = int(pan_y * max(0, ih - ch))
    cx = max(0, min(cx, iw - cw))
    cy = max(0, min(cy, ih - ch))
    crop = img[cy:cy+ch, cx:cx+cw]
    return cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA)

def ease(t):
    return 0.5 - 0.5 * math.cos(t * math.pi)

# Precompute vignette
_Y, _X = np.ogrid[:H, :W]
_vig = np.clip(1.0 - 0.3 * np.sqrt(((_X-W/2)/(W/2))**2 + ((_Y-H/2)/(H/2))**2), 0.4, 1.0).astype(np.float32)

def postprocess(frame):
    f = frame.astype(np.float32)
    f[:,:,2] = np.clip(f[:,:,2] + 12, 0, 255)
    f[:,:,1] = np.clip(f[:,:,1] + 4, 0, 255)
    f[:,:,0] = np.clip(f[:,:,0] - 6, 0, 255)
    for c in range(3):
        f[:,:,c] *= _vig
    return np.clip(f, 0, 255).astype(np.uint8)

print("=" * 50)
print("예인 인트로 데모 (자막 없음, 영상 효과만)")
print(f"Output: {W}x{H} @ {FPS}fps")
print("=" * 50)

# Load
print("\nLoading images...")
img_seated = load_img(os.path.join(POSES, 'full_seated.png'))
img_smile  = load_img(os.path.join(POSES, 'pose_00_smile_front.png'))
img_mic    = load_img(os.path.join(POSES, 'pose_08_mic_hold.png'))
img_down   = load_img(os.path.join(POSES, 'pose_07_look_down.png'))
img_piano  = load_img(os.path.join(POSES, 'pose_03_piano_mic.png'))
img_side   = load_img(os.path.join(POSES, 'pose_05_profile_right.png'))
img_soft   = load_img(os.path.join(POSES, 'pose_06_smile_soft.png'))

tmp_path = os.path.join(OUTPUT, 'demo_clean_raw.mp4')
final_path = os.path.join(OUTPUT, 'demo_intro_clean.mp4')
writer = cv2.VideoWriter(tmp_path, cv2.VideoWriter_fourcc(*'mp4v'), FPS, (W, H))
count = 0
prev = None

def w(frame):
    global count, prev
    frame = postprocess(frame)
    writer.write(frame)
    prev = frame.copy()
    count += 1

def xfade(img, zoom, px, py, n=15):
    global count, prev
    if prev is None: return
    target = postprocess(get_frame(img, zoom, px, py))
    for i in range(n):
        a = (i+1)/n
        writer.write(cv2.addWeighted(prev, 1-a, target, a, 0))
        count += 1
    prev = target.copy()

# Scene 1: 의자에 앉는 모습 (2.5s) - 줌인
print("[1/7] Seated - zoom in...")
n = int(2.5 * FPS)
for i in range(n):
    t = ease(i/(n-1))
    fade = min(1.0, i/(FPS*0.7))
    frame = get_frame(img_seated, 1.0+0.2*t, 0.5, 0.3+0.2*t)
    frame = (frame.astype(np.float32) * fade).astype(np.uint8)
    w(frame)

# Scene 2: 마이크 세팅 (2s) - 패닝
xfade(img_mic, 1.1, 0.3, 0.4)
print("[2/7] Mic setup - pan...")
n = int(2.0 * FPS)
for i in range(n):
    t = ease(i/(n-1))
    w(get_frame(img_mic, 1.1+0.05*t, 0.3+0.3*t, 0.4+0.1*t))

# Scene 3: 인사 - 밝은 표정 (2s)
xfade(img_smile, 1.15, 0.5, 0.45)
print("[3/7] Greeting smile...")
n = int(2.0 * FPS)
for i in range(n):
    t = ease(i/(n-1))
    w(get_frame(img_smile, 1.15+0.05*t, 0.5, 0.45+0.05*t))

# Scene 4: 허밍 - 눈 내리깔기 (2s)
xfade(img_down, 1.2, 0.5, 0.4)
print("[4/7] Humming - eyes down...")
n = int(2.0 * FPS)
for i in range(n):
    t = ease(i/(n-1))
    w(get_frame(img_down, 1.2+0.05*t, 0.5, 0.4+0.1*t))

# Scene 5: 노래 시작 - 측면 (1.5s)
xfade(img_side, 1.1, 0.4, 0.5)
print("[5/7] Singing start - side view...")
n = int(1.5 * FPS)
for i in range(n):
    t = ease(i/(n-1))
    w(get_frame(img_side, 1.1+0.08*t, 0.4+0.1*t, 0.5))

# Scene 6: 노래 중 - 부드러운 미소 (2s) breathing
xfade(img_soft, 1.0, 0.5, 0.5)
print("[6/7] Singing - soft smile (breathing)...")
n = int(2.0 * FPS)
for i in range(n):
    t = i/n
    zoom = 1.0 + 0.015 * math.sin(2*math.pi*1.5*t)
    w(get_frame(img_soft, zoom, 0.5, 0.5))

# Scene 7: 노래 정지 - 피아노 포즈 (3s) breathing
xfade(img_piano, 1.0, 0.5, 0.5)
print("[7/7] Singing still - piano pose (breathing)...")
n = int(3.0 * FPS)
for i in range(n):
    t = i/n
    zoom = 1.0 + 0.012 * math.sin(2*math.pi*1.0*t)
    frame = get_frame(img_piano, zoom, 0.5, 0.5)
    # Fade out last 1s
    remaining = n - i
    if remaining < FPS:
        fade = remaining / FPS
        frame = (frame.astype(np.float32) * fade).astype(np.uint8)
    w(frame)

writer.release()
dur = count/FPS
print(f"\nTotal: {count} frames, {dur:.1f}s")

print("Encoding H.264...")
subprocess.run([
    'ffmpeg', '-y', '-i', tmp_path,
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '22',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
    final_path
], capture_output=True)

if os.path.exists(final_path):
    mb = os.path.getsize(final_path)/(1024*1024)
    try: os.remove(tmp_path)
    except: pass
    print(f"\n{'='*50}")
    print(f"완료! {final_path}")
    print(f"{dur:.1f}초 / {mb:.1f}MB / {W}x{H}")
    print(f"{'='*50}")
