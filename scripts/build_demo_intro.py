"""
예인 인트로 데모 영상 생성
- 의자에 앉은 모습 (Ken Burns zoom in)
- 마이크 세팅 모습 (Ken Burns pan)
- "안녕하세요, 예인입니다" 인사 (텍스트 + 표정)
- 허밍 시작 + 눈 감기 (fade to still)
- 노래하는 사진 정지 (breathing effect)
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from video_effects import *

BASE = os.path.dirname(os.path.dirname(__file__))
POSES = os.path.join(BASE, 'video', 'poses')
OUTPUT = os.path.join(BASE, 'video', 'output')
os.makedirs(OUTPUT, exist_ok=True)

FONT_PATH = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'

def add_korean_text(frame, text, position='bottom_center', font_size=42,
                    color=(255,255,255), bg_opacity=0.5):
    """한글 텍스트 오버레이 with semi-transparent background"""
    from PIL import Image, ImageDraw, ImageFont

    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    overlay = Image.new('RGBA', pil_img.size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)

    font = ImageFont.truetype(FONT_PATH, font_size)
    bbox = draw.textbbox((0,0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    if position == 'bottom_center':
        x = (OUTPUT_W - tw) // 2
        y = OUTPUT_H - th - 80
    elif position == 'center':
        x = (OUTPUT_W - tw) // 2
        y = (OUTPUT_H - th) // 2
    elif position == 'top_center':
        x = (OUTPUT_W - tw) // 2
        y = 50

    padding = 16
    draw.rounded_rectangle(
        [x - padding, y - padding, x + tw + padding, y + th + padding],
        radius=8,
        fill=(0, 0, 0, int(255 * bg_opacity))
    )
    draw.text((x, y), text, font=font, fill=(*color, 255))

    composite = Image.alpha_composite(pil_img.convert('RGBA'), overlay)
    return cv2.cvtColor(np.array(composite.convert('RGB')), cv2.COLOR_RGB2BGR)


print("=" * 50)
print("예인 인트로 데모 영상 생성 시작")
print("=" * 50)

# Load images
print("\n[1/6] Loading images...")
img_seated = load_image(os.path.join(POSES, 'full_seated.png'))
img_smile = load_image(os.path.join(POSES, 'pose_00_smile_front.png'))
img_mic = load_image(os.path.join(POSES, 'pose_08_mic_hold.png'))
img_side = load_image(os.path.join(POSES, 'pose_05_profile_right.png'))
img_down = load_image(os.path.join(POSES, 'pose_07_look_down.png'))
img_piano = load_image(os.path.join(POSES, 'pose_03_piano_mic.png'))

all_frames = []

# ─── Scene 1: 의자에 앉는 모습 (2초) ─────────────────────────
print("[2/6] Scene 1: Sitting down (Ken Burns zoom in)...")
scene1 = ken_burns(img_seated, duration_sec=2.5,
                   zoom_start=1.0, zoom_end=1.2,
                   pan_start=(0.5, 0.3), pan_end=(0.5, 0.5))
scene1 = fade_in(scene1, duration_frames=20)
all_frames.extend(scene1)

# ─── Scene 2: 마이크 세팅 (2초) ──────────────────────────────
print("[3/6] Scene 2: Mic setup (Ken Burns pan)...")
scene2 = ken_burns(img_mic, duration_sec=2.0,
                   zoom_start=1.1, zoom_end=1.15,
                   pan_start=(0.3, 0.4), pan_end=(0.6, 0.5))
# crossfade from scene 1
transition_frames = 20
overlap = min(transition_frames, len(all_frames), len(scene2))
for i in range(overlap):
    alpha = i / overlap
    idx = len(all_frames) - overlap + i
    all_frames[idx] = cv2.addWeighted(all_frames[idx], 1-alpha, scene2[i], alpha, 0)
all_frames.extend(scene2[overlap:])

# ─── Scene 3: 인사 "안녕하세요, 예인입니다" (2.5초) ──────────
print("[4/6] Scene 3: Greeting with text...")
scene3 = ken_burns(img_smile, duration_sec=2.5,
                   zoom_start=1.15, zoom_end=1.2,
                   pan_start=(0.5, 0.45), pan_end=(0.5, 0.5))

# Add greeting text with fade in/out
for i, frame in enumerate(scene3):
    t = i / len(scene3)
    # Text fades in at 20%, stays, fades out at 80%
    if t < 0.2:
        text_alpha = t / 0.2
    elif t > 0.8:
        text_alpha = (1.0 - t) / 0.2
    else:
        text_alpha = 1.0

    if text_alpha > 0.05:
        scene3[i] = add_korean_text(frame, "안녕하세요, 예인입니다 ♪",
                                     position='bottom_center',
                                     font_size=48, bg_opacity=0.4 * text_alpha)

# crossfade
overlap = 15
for i in range(overlap):
    alpha = i / overlap
    idx = len(all_frames) - overlap + i
    all_frames[idx] = cv2.addWeighted(all_frames[idx], 1-alpha, scene3[i], alpha, 0)
all_frames.extend(scene3[overlap:])

# ─── Scene 4: 허밍 시작 + 눈 감기 (2초) ─────────────────────
print("[5/6] Scene 4: Humming start - eyes closing...")
scene4 = ken_burns(img_down, duration_sec=2.0,
                   zoom_start=1.2, zoom_end=1.25,
                   pan_start=(0.5, 0.4), pan_end=(0.5, 0.5))

# Add subtle "♪ humming... ♪" text
for i, frame in enumerate(scene4):
    t = i / len(scene4)
    if t > 0.3:
        text_alpha = min(1.0, (t - 0.3) / 0.3)
        scene4[i] = add_korean_text(frame, "♪  ~  ♪",
                                     position='bottom_center',
                                     font_size=36,
                                     color=(220, 200, 180),
                                     bg_opacity=0.3 * text_alpha)

overlap = 20
for i in range(overlap):
    alpha = i / overlap
    idx = len(all_frames) - overlap + i
    all_frames[idx] = cv2.addWeighted(all_frames[idx], 1-alpha, scene4[i], alpha, 0)
all_frames.extend(scene4[overlap:])

# ─── Scene 5: 노래하는 정지 이미지 + breathing (3초) ─────────
print("[6/6] Scene 5: Singing still with breathing effect...")
scene5 = breathing_effect(img_piano, duration_sec=3.0,
                          intensity=0.015, cycles=1.5)

# Add song title overlay
for i, frame in enumerate(scene5):
    t = i / len(scene5)
    if t < 0.15:
        text_alpha = t / 0.15
    else:
        text_alpha = max(0, 1.0 - (t - 0.15) / 0.4)

    if text_alpha > 0.05:
        scene5[i] = add_korean_text(frame, "♪ Little Eyes ♪",
                                     position='bottom_center',
                                     font_size=40,
                                     color=(255, 240, 220),
                                     bg_opacity=0.35 * text_alpha)

overlap = 25
for i in range(overlap):
    alpha = i / overlap
    idx = len(all_frames) - overlap + i
    all_frames[idx] = cv2.addWeighted(all_frames[idx], 1-alpha, scene5[i], alpha, 0)
all_frames.extend(scene5[overlap:])

# ─── Post-processing: Cafe look ──────────────────────────────
print("\nApplying cafe color grade...")
all_frames = apply_cafe_look(all_frames)

# ─── Write output ─────────────────────────────────────────────
output_path = os.path.join(OUTPUT, 'demo_intro.mp4')
print(f"\nWriting video: {output_path}")
write_video(all_frames, output_path)

duration = len(all_frames) / FPS
print(f"\n{'='*50}")
print(f"완료! 총 {duration:.1f}초 ({len(all_frames)} frames)")
print(f"출력: {output_path}")
print(f"{'='*50}")
