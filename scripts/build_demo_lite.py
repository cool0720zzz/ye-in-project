"""
예인 인트로 데모 - 메모리 최적화 버전
프레임을 메모리에 쌓지 않고 바로 VideoWriter에 씀
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

W, H = 1280, 720  # 720p for memory efficiency
FPS = 24
FONT = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'

def load_img(path):
    img = cv2.imread(path)
    h, w = img.shape[:2]
    scale = max(W/w, H/h) * 1.3  # extra margin for zoom
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

def warm_vignette(frame):
    """Combined warm grade + vignette in one pass"""
    result = frame.astype(np.float32)
    # Warm
    result[:,:,2] = np.clip(result[:,:,2] + 12, 0, 255)
    result[:,:,1] = np.clip(result[:,:,1] + 4, 0, 255)
    result[:,:,0] = np.clip(result[:,:,0] - 6, 0, 255)
    # Vignette (precomputed would be better but this is simple)
    Y, X = np.ogrid[:H, :W]
    dist = np.sqrt(((X - W/2)/(W/2))**2 + ((Y - H/2)/(H/2))**2)
    vig = np.clip(1.0 - 0.3 * dist, 0.4, 1.0)
    for c in range(3):
        result[:,:,c] *= vig
    return np.clip(result, 0, 255).astype(np.uint8)

def put_text(frame, text, y_offset=None):
    """Simple text overlay using OpenCV (supports ASCII + basic shapes)"""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.9
    thickness = 2
    size = cv2.getTextSize(text, font, scale, thickness)[0]
    x = (W - size[0]) // 2
    y = y_offset if y_offset else H - 60
    # Background
    cv2.rectangle(frame, (x-12, y-size[1]-8), (x+size[0]+12, y+8), (0,0,0), -1)
    # Text
    cv2.putText(frame, text, (x, y), font, scale, (230, 220, 200), thickness, cv2.LINE_AA)
    return frame

def put_korean_text(frame, text, font_size=40):
    """Korean text using PIL with proper font"""
    from PIL import Image, ImageDraw, ImageFont

    # Convert BGR frame to RGB PIL Image
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb_frame).convert('RGBA')

    try:
        font = ImageFont.truetype(FONT, font_size)
    except Exception as e:
        print(f"Font error: {e}")
        return put_text(frame, text)

    # Create text overlay
    txt_layer = Image.new('RGBA', pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (W - tw) // 2
    y = H - th - 55

    # Background rectangle
    draw.rounded_rectangle(
        [x - 16, y - 12, x + tw + 16, y + th + 12],
        radius=8, fill=(0, 0, 0, 130)
    )
    # Text with shadow
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=(240, 230, 215, 255))

    # Composite and convert back to BGR
    result = Image.alpha_composite(pil, txt_layer)
    return cv2.cvtColor(np.array(result.convert('RGB')), cv2.COLOR_RGB2BGR)


# Precompute vignette mask
_vig_Y, _vig_X = np.ogrid[:H, :W]
_vig_dist = np.sqrt(((_vig_X - W/2)/(W/2))**2 + ((_vig_Y - H/2)/(H/2))**2)
_vig_mask = np.clip(1.0 - 0.3 * _vig_dist, 0.4, 1.0).astype(np.float32)

def fast_postprocess(frame):
    """Fast warm + vignette using precomputed mask"""
    f = frame.astype(np.float32)
    f[:,:,2] = np.clip(f[:,:,2] + 12, 0, 255)  # R+
    f[:,:,1] = np.clip(f[:,:,1] + 4, 0, 255)   # G+
    f[:,:,0] = np.clip(f[:,:,0] - 6, 0, 255)   # B-
    for c in range(3):
        f[:,:,c] *= _vig_mask
    return np.clip(f, 0, 255).astype(np.uint8)


print("=" * 50)
print("예인 인트로 데모 (최적화 버전)")
print(f"Output: {W}x{H} @ {FPS}fps")
print("=" * 50)

# Load images
print("\nLoading images...")
img_seated = load_img(os.path.join(POSES, 'full_seated.png'))
img_smile = load_img(os.path.join(POSES, 'pose_00_smile_front.png'))
img_mic = load_img(os.path.join(POSES, 'pose_08_mic_hold.png'))
img_side = load_img(os.path.join(POSES, 'pose_05_profile_right.png'))
img_down = load_img(os.path.join(POSES, 'pose_07_look_down.png'))
img_piano = load_img(os.path.join(POSES, 'pose_03_piano_mic.png'))

# Setup video writer
tmp_path = os.path.join(OUTPUT, 'demo_intro_raw.mp4')
final_path = os.path.join(OUTPUT, 'demo_intro.mp4')
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
writer = cv2.VideoWriter(tmp_path, fourcc, FPS, (W, H))
total_written = 0
prev_frame = None

def write_frame(frame, with_postprocess=True):
    global total_written, prev_frame
    if with_postprocess:
        frame = fast_postprocess(frame)
    writer.write(frame)
    prev_frame = frame.copy()
    total_written += 1

def write_crossfade(img_new, zoom, px, py, n_frames=12):
    """Crossfade from prev_frame to new image"""
    global prev_frame
    if prev_frame is None:
        return
    target = fast_postprocess(get_frame(img_new, zoom, px, py))
    for i in range(n_frames):
        alpha = (i+1) / n_frames
        blended = cv2.addWeighted(prev_frame, 1-alpha, target, alpha, 0)
        writer.write(blended)
    global total_written
    total_written += n_frames
    prev_frame = target.copy()


# ─── Scene 1: 의자에 앉는 모습 (2.5s) ────────────────────────
print("[1/5] Sitting down - Ken Burns zoom in...")
n = int(2.5 * FPS)
for i in range(n):
    t = ease(i / (n-1))
    zoom = 1.0 + 0.2 * t
    fade = min(1.0, i / (FPS * 0.7))  # fade in over 0.7s
    frame = get_frame(img_seated, zoom, 0.5, 0.3 + 0.2*t)
    frame = (frame.astype(np.float32) * fade).astype(np.uint8)
    write_frame(frame)

# ─── Crossfade to Scene 2 ────────────────────────────────────
write_crossfade(img_mic, 1.1, 0.3, 0.4)

# ─── Scene 2: 마이크 세팅 (2s) ───────────────────────────────
print("[2/5] Mic setup - Ken Burns pan...")
n = int(2.0 * FPS)
for i in range(n):
    t = ease(i / (n-1))
    frame = get_frame(img_mic, 1.1 + 0.05*t, 0.3 + 0.3*t, 0.4 + 0.1*t)
    write_frame(frame)

# ─── Crossfade to Scene 3 ────────────────────────────────────
write_crossfade(img_smile, 1.15, 0.5, 0.45)

# ─── Scene 3: 인사 (2.5s) ────────────────────────────────────
print("[3/5] Greeting - '안녕하세요, 예인입니다'...")
n = int(2.5 * FPS)
for i in range(n):
    t = ease(i / (n-1))
    frame = get_frame(img_smile, 1.15 + 0.05*t, 0.5, 0.45 + 0.05*t)
    frame = fast_postprocess(frame)

    # Text fade: in at 20%, out at 80%
    tt = i / n
    if tt < 0.2:
        text_show = tt / 0.2
    elif tt > 0.8:
        text_show = (1.0 - tt) / 0.2
    else:
        text_show = 1.0

    if text_show > 0.1:
        frame = put_korean_text(frame, "안녕하세요, 예인입니다 ♪", font_size=42)

    writer.write(frame)
    prev_frame = frame.copy()
    total_written += 1

# ─── Crossfade to Scene 4 ────────────────────────────────────
write_crossfade(img_down, 1.2, 0.5, 0.4)

# ─── Scene 4: 허밍 시작 (2s) ─────────────────────────────────
print("[4/5] Humming start - eyes closing...")
n = int(2.0 * FPS)
for i in range(n):
    t = ease(i / (n-1))
    frame = get_frame(img_down, 1.2 + 0.05*t, 0.5, 0.4 + 0.1*t)
    frame = fast_postprocess(frame)

    tt = i / n
    if tt > 0.3:
        frame = put_text(frame, "~ humming ~")

    writer.write(frame)
    prev_frame = frame.copy()
    total_written += 1

# ─── Crossfade to Scene 5 ────────────────────────────────────
write_crossfade(img_piano, 1.0, 0.5, 0.5)

# ─── Scene 5: 노래 정지 + breathing (3s) ─────────────────────
print("[5/5] Singing still - breathing effect...")
n = int(3.0 * FPS)
for i in range(n):
    t = i / n
    zoom = 1.0 + 0.015 * math.sin(2 * math.pi * 1.5 * t)
    frame = get_frame(img_piano, zoom, 0.5, 0.5)
    frame = fast_postprocess(frame)

    # Song title fade in then out
    if t < 0.15:
        ta = t / 0.15
    elif t < 0.5:
        ta = 1.0
    else:
        ta = max(0, 1.0 - (t - 0.5) / 0.3)

    if ta > 0.1:
        frame = put_text(frame, "Little Eyes")

    writer.write(frame)
    total_written += 1

# Done
writer.release()
duration = total_written / FPS
print(f"\nRaw video: {total_written} frames, {duration:.1f}s")

# Re-encode with H.264
print("Re-encoding with H.264...")
subprocess.run([
    'ffmpeg', '-y', '-i', tmp_path,
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
    final_path
], capture_output=True)

if os.path.exists(final_path):
    size_mb = os.path.getsize(final_path) / (1024*1024)
    try:
        os.remove(tmp_path)
    except:
        pass  # ignore permission errors on tmp cleanup
    print(f"\n{'='*50}")
    print(f"완료!")
    print(f"파일: {final_path}")
    print(f"길이: {duration:.1f}초")
    print(f"크기: {size_mb:.1f}MB")
    print(f"해상도: {W}x{H} @ {FPS}fps")
    print(f"{'='*50}")
else:
    print("ERROR: ffmpeg encoding failed")
    print(f"Raw file at: {tmp_path}")
