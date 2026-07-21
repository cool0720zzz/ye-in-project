"""
예인 카페음악 프로젝트 - 이미지→영상 변환 엔진
코드만으로 구현 가능한 영상 효과 모듈

사용 가능한 기법:
1. Ken Burns Effect - 이미지에 천천히 줌인/줌아웃 + 패닝
2. Crossfade Transition - 포즈 간 부드러운 전환
3. Parallax Layers - 전경/배경 분리 후 깊이감 있는 움직임
4. Text Overlay - 자막, 가사, 인사 텍스트
5. Vignette + Color Grade - 따뜻한 카페 톤 보정
6. Breathing Effect - 미세한 확대/축소 반복으로 정지 이미지에 생동감
7. Film Grain / Noise - 아날로그 감성 노이즈 추가
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import subprocess
import math

# Output settings
OUTPUT_W, OUTPUT_H = 1920, 1080
FPS = 30


def load_image(path, fit_width=OUTPUT_W, fit_height=OUTPUT_H):
    """이미지를 로드하고 출력 해상도에 맞게 리사이즈"""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Cannot load: {path}")

    h, w = img.shape[:2]
    # Scale to fill the output frame (cover, not contain)
    scale = max(fit_width / w, fit_height / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    return img


def crop_center(img, out_w=OUTPUT_W, out_h=OUTPUT_H):
    """중앙 크롭"""
    h, w = img.shape[:2]
    x = (w - out_w) // 2
    y = (h - out_h) // 2
    return img[max(0,y):y+out_h, max(0,x):x+out_w]


# ─── Effect 1: Ken Burns ─────────────────────────────────────
def ken_burns(img, duration_sec, zoom_start=1.0, zoom_end=1.15,
              pan_start=(0.5, 0.5), pan_end=(0.5, 0.5)):
    """
    Ken Burns 효과 - 천천히 줌 + 패닝
    pan: (0.5, 0.5) = 중앙, (0.0, 0.0) = 좌상단, (1.0, 1.0) = 우하단
    """
    frames = []
    total_frames = int(duration_sec * FPS)
    h, w = img.shape[:2]

    for i in range(total_frames):
        t = i / max(total_frames - 1, 1)  # 0.0 ~ 1.0
        # Ease in-out
        t_ease = 0.5 - 0.5 * math.cos(t * math.pi)

        zoom = zoom_start + (zoom_end - zoom_start) * t_ease
        px = pan_start[0] + (pan_end[0] - pan_start[0]) * t_ease
        py = pan_start[1] + (pan_end[1] - pan_start[1]) * t_ease

        crop_w = int(OUTPUT_W / zoom)
        crop_h = int(OUTPUT_H / zoom)

        cx = int(px * (w - crop_w))
        cy = int(py * (h - crop_h))
        cx = max(0, min(cx, w - crop_w))
        cy = max(0, min(cy, h - crop_h))

        cropped = img[cy:cy+crop_h, cx:cx+crop_w]
        frame = cv2.resize(cropped, (OUTPUT_W, OUTPUT_H), interpolation=cv2.INTER_LANCZOS4)
        frames.append(frame)

    return frames


# ─── Effect 2: Crossfade ─────────────────────────────────────
def crossfade(frames_a, frames_b, overlap_frames=30):
    """두 프레임 시퀀스를 크로스페이드로 연결"""
    result = list(frames_a[:-overlap_frames])

    for i in range(overlap_frames):
        alpha = i / overlap_frames
        blended = cv2.addWeighted(frames_a[-(overlap_frames-i)], 1-alpha,
                                   frames_b[i], alpha, 0)
        result.append(blended)

    result.extend(frames_b[overlap_frames:])
    return result


# ─── Effect 3: Breathing Effect ──────────────────────────────
def breathing_effect(img, duration_sec, intensity=0.02, cycles=2):
    """미세한 줌 인/아웃 반복 - 정지 이미지에 생동감"""
    frames = []
    total_frames = int(duration_sec * FPS)
    h, w = img.shape[:2]

    for i in range(total_frames):
        t = i / total_frames
        zoom = 1.0 + intensity * math.sin(2 * math.pi * cycles * t)

        crop_w = int(OUTPUT_W / zoom)
        crop_h = int(OUTPUT_H / zoom)
        cx = (w - crop_w) // 2
        cy = (h - crop_h) // 2

        cropped = img[cy:cy+crop_h, cx:cx+crop_w]
        frame = cv2.resize(cropped, (OUTPUT_W, OUTPUT_H), interpolation=cv2.INTER_LANCZOS4)
        frames.append(frame)

    return frames


# ─── Effect 4: Warm Color Grade ──────────────────────────────
def warm_grade(frame, warmth=15, contrast=1.05):
    """따뜻한 카페 톤 색보정"""
    # Increase warmth (add to red/yellow, reduce blue)
    result = frame.astype(np.float32)
    result[:,:,2] = np.clip(result[:,:,2] + warmth, 0, 255)      # Red +
    result[:,:,1] = np.clip(result[:,:,1] + warmth * 0.3, 0, 255) # Green slight +
    result[:,:,0] = np.clip(result[:,:,0] - warmth * 0.5, 0, 255) # Blue -

    # Contrast
    result = np.clip((result - 128) * contrast + 128, 0, 255)
    return result.astype(np.uint8)


# ─── Effect 5: Vignette ──────────────────────────────────────
def add_vignette(frame, strength=0.4):
    """비네트 효과 - 가장자리 어둡게"""
    h, w = frame.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2

    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    max_dist = np.sqrt(cx**2 + cy**2)
    vignette = 1 - strength * (dist / max_dist)**2

    result = frame.astype(np.float32)
    for c in range(3):
        result[:,:,c] *= vignette
    return np.clip(result, 0, 255).astype(np.uint8)


# ─── Effect 6: Film Grain ────────────────────────────────────
def add_grain(frame, intensity=10):
    """필름 그레인 노이즈"""
    noise = np.random.normal(0, intensity, frame.shape).astype(np.float32)
    result = np.clip(frame.astype(np.float32) + noise, 0, 255)
    return result.astype(np.uint8)


# ─── Effect 7: Text Overlay (Korean + English) ───────────────
def add_text_overlay(frame, text, position='bottom_center',
                     font_size=36, color=(255,255,255), opacity=0.9):
    """텍스트 오버레이 (PIL 사용 - 한글 지원)"""
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    overlay = Image.new('RGBA', pil_img.size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", font_size)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0,0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    if position == 'bottom_center':
        x = (OUTPUT_W - tw) // 2
        y = OUTPUT_H - th - 60
    elif position == 'center':
        x = (OUTPUT_W - tw) // 2
        y = (OUTPUT_H - th) // 2
    elif position == 'top_center':
        x = (OUTPUT_W - tw) // 2
        y = 40
    else:
        x, y = position

    # Shadow
    draw.text((x+2, y+2), text, font=font, fill=(0,0,0,int(200*opacity)))
    # Main text
    alpha = int(255 * opacity)
    draw.text((x, y), text, font=font, fill=(*color, alpha))

    composite = Image.alpha_composite(pil_img.convert('RGBA'), overlay)
    return cv2.cvtColor(np.array(composite.convert('RGB')), cv2.COLOR_RGB2BGR)


# ─── Effect 8: Fade In/Out ───────────────────────────────────
def fade_in(frames, duration_frames=30):
    """페이드 인"""
    result = []
    for i, frame in enumerate(frames):
        if i < duration_frames:
            alpha = i / duration_frames
            result.append((frame * alpha).astype(np.uint8))
        else:
            result.append(frame)
    return result


def fade_out(frames, duration_frames=30):
    """페이드 아웃"""
    result = []
    n = len(frames)
    for i, frame in enumerate(frames):
        remaining = n - i
        if remaining < duration_frames:
            alpha = remaining / duration_frames
            result.append((frame * alpha).astype(np.uint8))
        else:
            result.append(frame)
    return result


# ─── Effect 9: Slide Transition ──────────────────────────────
def slide_transition(img_from, img_to, duration_sec=1.0, direction='left'):
    """슬라이드 전환"""
    frames = []
    total_frames = int(duration_sec * FPS)

    for i in range(total_frames):
        t = i / max(total_frames - 1, 1)
        t_ease = 0.5 - 0.5 * math.cos(t * math.pi)

        canvas = np.zeros((OUTPUT_H, OUTPUT_W, 3), dtype=np.uint8)

        if direction == 'left':
            offset = int(OUTPUT_W * t_ease)
            # Old image sliding out
            if OUTPUT_W - offset > 0:
                canvas[:, :OUTPUT_W-offset] = crop_center(img_from)[:, offset:]
            # New image sliding in
            if offset > 0:
                canvas[:, OUTPUT_W-offset:] = crop_center(img_to)[:, :offset]

        frames.append(canvas)
    return frames


# ─── Video Writer ─────────────────────────────────────────────
def write_video(frames, output_path, fps=FPS):
    """프레임 리스트를 비디오 파일로 출력"""
    if not frames:
        print("No frames to write!")
        return

    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    for frame in frames:
        out.write(frame)

    out.release()
    print(f"Written {len(frames)} frames to {output_path} ({len(frames)/fps:.1f}s)")

    # Re-encode with ffmpeg for better compatibility
    final_path = output_path.replace('.mp4', '_final.mp4')
    subprocess.run([
        'ffmpeg', '-y', '-i', output_path,
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        final_path
    ], capture_output=True)

    if os.path.exists(final_path):
        os.replace(final_path, output_path)
        print(f"Re-encoded with H.264: {output_path}")


# ─── Post-processing pipeline ────────────────────────────────
def apply_cafe_look(frames):
    """카페 분위기 후처리 파이프라인"""
    processed = []
    for frame in frames:
        frame = warm_grade(frame, warmth=12)
        frame = add_vignette(frame, strength=0.3)
        frame = add_grain(frame, intensity=5)
        processed.append(frame)
    return processed


if __name__ == "__main__":
    print("예인 Video Effects Engine loaded.")
    print(f"Output: {OUTPUT_W}x{OUTPUT_H} @ {FPS}fps")
    print("Available effects: ken_burns, crossfade, breathing_effect,")
    print("  warm_grade, add_vignette, add_grain, add_text_overlay,")
    print("  fade_in, fade_out, slide_transition, apply_cafe_look")
