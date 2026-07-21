#!/usr/bin/env python3
"""
예인 카페음악 프로젝트 — 2시간 영상 자동 조립 스크립트

사용법:
    python3 scripts/assemble_full_video.py

필요한 소스 파일:
    music/vocals/A01.mp3 ~ A15.mp3      (예인의 이야기 15곡)
    music/vocals/B01.mp3 ~ B15.mp3      (청자에게 전하는 이야기 15곡)
    music/instrumental/C01.mp3 ~ C08.mp3 (인스트루멘탈 8곡)
    music/voice/greeting_voice.wav       (초기 1회 셋팅 TTS)
    music/voice/break_voice.wav          (초기 1회 셋팅 TTS)
    video/clips/intro_sit_down.mp4       (Kling 생성)
    video/clips/intro_mic_setup.mp4      (Kling 생성)
    video/clips/intro_greeting.mp4       (SadTalker 생성)
    video/clips/humming_eyes_close_a.mp4 (Kling 생성)
    video/clips/humming_eyes_close_b.mp4 (Kling 생성)
    video/clips/humming_eyes_close_c.mp4 (Kling 생성)
    video/clips/break_ment.mp4           (SadTalker 생성)
    video/clips/break_exit.mp4           (Kling 생성)
    video/clips/break_return.mp4         (Kling 생성)
    video/poses/pose_*.png               (이미 추출됨)

이 스크립트가 하는 일:
    1. 오디오 노멀라이즈
    2. 각 곡에 Breathing 정지 영상 생성 (곡 길이에 맞춤)
    3. 타임라인 순서대로 모든 세그먼트 조립
    4. TTS 음성 + 모션 클립 삽입
    5. 최종 1080p H.264 렌더링
    6. 유튜브 타임스탬프 자동 생성
"""

import os
import sys
import json
import glob
import math
import subprocess
import shutil

# ─── 경로 설정 ──────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_VOCALS = os.path.join(BASE, 'music', 'vocals')
MUSIC_INST = os.path.join(BASE, 'music', 'instrumental')
MUSIC_VOICE = os.path.join(BASE, 'music', 'voice')
VIDEO_CLIPS = os.path.join(BASE, 'video', 'clips')
VIDEO_POSES = os.path.join(BASE, 'video', 'poses')
VIDEO_SEGMENTS = os.path.join(BASE, 'video', 'segments')
VIDEO_OUTPUT = os.path.join(BASE, 'video', 'output')
TEMP_DIR = os.path.join(BASE, 'video', '_temp')

for d in [VIDEO_SEGMENTS, VIDEO_OUTPUT, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

# ─── 설정 ───────────────────────────────────────────────────
W, H = 1280, 720  # 720p (1080p로 올리려면 1920, 1080)
FPS = 24

# 포즈 이미지 — 보컬곡마다 다른 포즈를 돌아가며 사용
SINGING_POSES = [
    'pose_03_piano_mic.png',
    'pose_05_profile_right.png',
    'pose_06_smile_soft.png',
    'pose_08_mic_hold.png',
    'pose_07_look_down.png',
    'pose_02_gaze_side.png',
]

# 인스트루멘탈 배경 — 전신 이미지 사용
INST_BG = 'full_seated.png'

# 허밍 클립 로테이션
HUMMING_CLIPS = [
    'humming_eyes_close_a.mp4',
    'humming_eyes_close_b.mp4',
    'humming_eyes_close_c.mp4',
]

# ─── 세트리스트 (기획서 기준) ────────────────────────────────
# 순서: 예인A 7곡 → 쉬는시간 2곡 → 청자B 7곡 → 쉬는시간 2곡
#       예인A 8곡 → 쉬는시간 2곡 → 청자B 8곡 → 쉬는시간 2곡
SETLIST = [
    # Block 1: 예인의 이야기 #1
    {'type': 'vocal', 'songs': ['A01','A02','A03','A04','A05','A06','A07']},
    {'type': 'break', 'songs': ['C01','C02']},
    # Block 2: 청자에게 전하는 이야기 #1
    {'type': 'vocal', 'songs': ['B01','B02','B03','B04','B05','B06','B07']},
    {'type': 'break', 'songs': ['C03','C04']},
    # Block 3: 예인의 이야기 #2
    {'type': 'vocal', 'songs': ['A08','A09','A10','A11','A12','A13','A14','A15']},
    {'type': 'break', 'songs': ['C05','C06']},
    # Block 4: 청자에게 전하는 이야기 #2
    {'type': 'vocal', 'songs': ['B08','B09','B10','B11','B12','B13','B14','B15']},
    {'type': 'break', 'songs': ['C07','C08']},
]

# 곡 제목 (타임스탬프용)
SONG_TITLES = {
    'A01': 'Little Eyes', 'A02': "Daddy's Warm Hands", 'A03': 'Today Feels Like Home',
    'A04': 'Morning Light', 'A05': 'Old Bookstore', 'A06': "Grandma's Kitchen",
    'A07': 'Rainy Window', 'A08': 'Sunday Afternoon', 'A09': 'Paper Cranes',
    'A10': 'Warm Milk', 'A11': 'Street Cat', 'A12': 'Falling Leaves',
    'A13': 'First Snow', 'A14': "Mom's Lullaby", 'A15': 'Bread and Butter',
    'B01': 'You Did Well Today', 'B02': "I'm Rooting for You", 'B03': 'Brighter Tomorrow',
    'B04': 'Take Your Time', 'B05': "You're Not Alone", 'B06': 'Rest a Little',
    'B07': 'Small Steps Count', 'B08': 'Your Smile Matters', 'B09': 'Keep Going',
    'B10': "It's Okay to Cry", 'B11': 'Dream a Little Dream', 'B12': 'Someone Believes in You',
    'B13': 'After the Rain', 'B14': 'Just Breathe', 'B15': 'Goodnight, Dear',
    'C01': 'Afternoon Brew', 'C02': 'Quiet Corner', 'C03': 'Sunset Walk',
    'C04': 'Gentle Stream', 'C05': 'Bookshelf Dust', 'C06': 'Window Seat',
    'C07': 'Midnight Tea', 'C08': 'Closing Time',
}


# ─── 유틸리티 함수 ──────────────────────────────────────────

def run_cmd(cmd, desc=""):
    """FFmpeg 명령 실행"""
    if desc:
        print(f"  {desc}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:200]}")
        return False
    return True


def get_duration(filepath):
    """미디어 파일 길이(초) 반환"""
    result = subprocess.run([
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_format', filepath
    ], capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except:
        return 0.0


def normalize_audio(input_path, output_path):
    """오디오 볼륨 노멀라이즈"""
    return run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-ar', '44100', '-ac', '2',
        output_path
    ], f"Normalizing {os.path.basename(input_path)}")


def find_audio(song_id):
    """곡 ID로 오디오 파일 찾기 (A01, B05, C03 등)"""
    if song_id.startswith('C'):
        base_dir = MUSIC_INST
    else:
        base_dir = MUSIC_VOCALS

    # 여러 패턴 시도
    for pattern in [f'{song_id}.*', f'{song_id}_*.*', f'*{song_id}*.*']:
        matches = glob.glob(os.path.join(base_dir, pattern))
        audio_matches = [m for m in matches if m.endswith(('.mp3', '.wav', '.m4a', '.ogg'))]
        if audio_matches:
            return audio_matches[0]
    return None


def make_breathing_video(pose_image, duration_sec, output_path):
    """정지 이미지에 Breathing 효과 적용한 영상 생성 (FFmpeg만 사용)"""
    # FFmpeg zoompan 필터로 미세한 줌 반복 (breathing 효과)
    # zoompan: z는 줌 레벨, d는 프레임 수
    total_frames = int(duration_sec * FPS)
    return run_cmd([
        'ffmpeg', '-y',
        '-loop', '1', '-i', pose_image,
        '-vf', (
            f"scale={W*2}:{H*2},"  # 2배 크기로 스케일 (줌 마진)
            f"zoompan=z='1.0+0.015*sin(2*PI*on/{FPS}/4)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s={W}x{H}:fps={FPS},"
            f"eq=brightness=0.03:saturation=1.1,"  # 약간 밝고 따뜻하게
            f"vignette=PI/4"  # 비네트
        ),
        '-t', str(duration_sec),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p',
        output_path
    ], f"Breathing video ({duration_sec:.0f}s)")


def make_still_video(image_path, duration_sec, output_path):
    """정지 이미지를 영상으로 변환 (인스트루멘탈용, 움직임 없음)"""
    return run_cmd([
        'ffmpeg', '-y',
        '-loop', '1', '-i', image_path,
        '-vf', (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"eq=brightness=0.02:saturation=1.05,"
            f"vignette=PI/5"
        ),
        '-t', str(duration_sec),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p',
        output_path
    ])


def merge_video_audio(video_path, audio_path, output_path):
    """영상 + 오디오 합성"""
    return run_cmd([
        'ffmpeg', '-y',
        '-i', video_path, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        output_path
    ])


def normalize_clip(input_path, output_path):
    """클립을 통일된 포맷으로 변환 (해상도, fps, 코덱)"""
    return run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '44100',
        '-pix_fmt', 'yuv420p', '-shortest',
        output_path
    ])


def add_audio_to_clip(video_path, audio_path, output_path):
    """무음 비디오 클립에 TTS 오디오 합성"""
    return run_cmd([
        'ffmpeg', '-y',
        '-i', video_path, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-map', '0:v:0', '-map', '1:a:0',
        '-shortest',
        output_path
    ])


def format_timestamp(seconds):
    """초 → HH:MM:SS 형식"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ─── 메인 파이프라인 ────────────────────────────────────────

def check_sources():
    """필요한 소스 파일 존재 여부 확인"""
    print("\n[CHECK] 소스 파일 확인 중...")
    missing = []
    found = []

    # 음악 파일
    for block in SETLIST:
        for song_id in block['songs']:
            path = find_audio(song_id)
            if path:
                found.append(f"  ✅ {song_id}: {os.path.basename(path)}")
            else:
                missing.append(f"  ❌ {song_id}: 음악 파일 없음")

    # 클립 파일
    required_clips = [
        'intro_sit_down.mp4', 'intro_mic_setup.mp4', 'intro_greeting.mp4',
        'humming_eyes_close_a.mp4', 'humming_eyes_close_b.mp4', 'humming_eyes_close_c.mp4',
        'break_ment.mp4', 'break_exit.mp4', 'break_return.mp4',
    ]
    for clip in required_clips:
        path = os.path.join(VIDEO_CLIPS, clip)
        if os.path.exists(path):
            found.append(f"  ✅ clips/{clip}")
        else:
            missing.append(f"  ❌ clips/{clip}")

    # TTS
    for voice in ['greeting_voice.wav', 'break_voice.wav']:
        path = os.path.join(MUSIC_VOICE, voice)
        if os.path.exists(path):
            found.append(f"  ✅ voice/{voice}")
        else:
            missing.append(f"  ❌ voice/{voice}")

    # 포즈 이미지
    for pose in SINGING_POSES + [INST_BG]:
        path = os.path.join(VIDEO_POSES, pose)
        if os.path.exists(path):
            found.append(f"  ✅ poses/{pose}")
        else:
            missing.append(f"  ❌ poses/{pose}")

    print(f"\n찾은 파일: {len(found)}개")
    for f in found[:5]:
        print(f)
    if len(found) > 5:
        print(f"  ... 외 {len(found)-5}개")

    if missing:
        print(f"\n누락된 파일: {len(missing)}개")
        for m in missing:
            print(m)
        return False

    print("\n모든 소스 파일 준비 완료! ✅")
    return True


def assemble():
    """전체 영상 자동 조립"""
    print("=" * 60)
    print("  예인 카페음악 — 자동 영상 조립 시작")
    print("=" * 60)

    # 소스 체크
    if not check_sources():
        print("\n⚠️  누락된 파일이 있습니다.")
        print("위 파일들을 준비한 후 다시 실행하세요.")
        print("(--force 옵션으로 있는 파일만으로 진행 가능)")
        if '--force' not in sys.argv:
            return

    segments = []       # 조립할 세그먼트 경로 리스트
    timestamps = []     # 유튜브 타임스탬프
    current_time = 0.0  # 현재 시간 (초)
    pose_idx = 0        # 포즈 로테이션 인덱스
    humming_idx = 0     # 허밍 클립 로테이션
    seg_num = 0         # 세그먼트 번호

    def add_segment(path, label=""):
        nonlocal current_time, seg_num
        dur = get_duration(path)
        if dur > 0:
            segments.append(path)
            if label:
                timestamps.append((current_time, label))
            current_time += dur
            seg_num += 1
            print(f"    [{seg_num:03d}] +{dur:.1f}s = {format_timestamp(current_time)}  {label or os.path.basename(path)}")
        return dur

    # ─── STEP 1: 오디오 노멀라이즈 ──────────────────────────
    print("\n[STEP 1] 오디오 노멀라이즈...")
    norm_dir = os.path.join(TEMP_DIR, 'normalized')
    os.makedirs(norm_dir, exist_ok=True)

    for block in SETLIST:
        for song_id in block['songs']:
            src = find_audio(song_id)
            if src:
                dst = os.path.join(norm_dir, f'{song_id}.mp3')
                if not os.path.exists(dst):
                    normalize_audio(src, dst)

    # ─── STEP 2: 인트로 ─────────────────────────────────────
    print("\n[STEP 2] 인트로 조립...")

    # 인트로 클립 노멀라이즈
    intro_clips = ['intro_sit_down.mp4', 'intro_mic_setup.mp4', 'intro_greeting.mp4']
    for clip_name in intro_clips:
        src = os.path.join(VIDEO_CLIPS, clip_name)
        dst = os.path.join(TEMP_DIR, f'norm_{clip_name}')
        if os.path.exists(src) and not os.path.exists(dst):
            normalize_clip(src, dst)

        if os.path.exists(dst):
            label = ""
            if clip_name == 'intro_sit_down.mp4':
                label = "인트로"
            add_segment(dst, label)

    # ─── STEP 3: 메인 블록 조립 ─────────────────────────────
    print("\n[STEP 3] 메인 블록 조립...")

    for block_i, block in enumerate(SETLIST):

        if block['type'] == 'vocal':
            # 보컬 블록
            block_label = "예인의 이야기" if block['songs'][0].startswith('A') else "청자에게 전하는 이야기"
            block_num = 1 if block_i < 2 else 2
            print(f"\n  ── {block_label} #{block_num} ({len(block['songs'])}곡) ──")

            for song_id in block['songs']:
                # 허밍 클립 삽입
                humming_file = HUMMING_CLIPS[humming_idx % len(HUMMING_CLIPS)]
                humming_src = os.path.join(VIDEO_CLIPS, humming_file)
                humming_norm = os.path.join(TEMP_DIR, f'norm_{humming_file}')
                if os.path.exists(humming_src) and not os.path.exists(humming_norm):
                    normalize_clip(humming_src, humming_norm)
                if os.path.exists(humming_norm):
                    add_segment(humming_norm)
                humming_idx += 1

                # 노래 영상 (Breathing) + 오디오
                audio_path = os.path.join(norm_dir, f'{song_id}.mp3')
                if os.path.exists(audio_path):
                    duration = get_duration(audio_path)
                    pose_file = SINGING_POSES[pose_idx % len(SINGING_POSES)]
                    pose_path = os.path.join(VIDEO_POSES, pose_file)
                    pose_idx += 1

                    # Breathing 영상 생성
                    breathing_path = os.path.join(VIDEO_SEGMENTS, f'{song_id}_breathing.mp4')
                    if not os.path.exists(breathing_path):
                        make_breathing_video(pose_path, duration, breathing_path)

                    # 영상 + 오디오 합성
                    merged_path = os.path.join(VIDEO_SEGMENTS, f'{song_id}_final.mp4')
                    if not os.path.exists(merged_path):
                        merge_video_audio(breathing_path, audio_path, merged_path)

                    title = SONG_TITLES.get(song_id, song_id)
                    add_segment(merged_path, f"{song_id} - {title}")

        elif block['type'] == 'break':
            # 쉬는 시간
            print(f"\n  ── 쉬는 시간 ({len(block['songs'])}곡) ──")

            # "쉬어갈게요" 멘트 + 퇴장
            ment_src = os.path.join(VIDEO_CLIPS, 'break_ment.mp4')
            ment_norm = os.path.join(TEMP_DIR, 'norm_break_ment.mp4')
            if os.path.exists(ment_src) and not os.path.exists(ment_norm):
                normalize_clip(ment_src, ment_norm)
            if os.path.exists(ment_norm):
                add_segment(ment_norm, "잠깐 쉬어갈게요")

            exit_src = os.path.join(VIDEO_CLIPS, 'break_exit.mp4')
            exit_norm = os.path.join(TEMP_DIR, 'norm_break_exit.mp4')
            if os.path.exists(exit_src) and not os.path.exists(exit_norm):
                normalize_clip(exit_src, exit_norm)
            if os.path.exists(exit_norm):
                add_segment(exit_norm)

            # 인스트루멘탈 곡
            for song_id in block['songs']:
                audio_path = os.path.join(norm_dir, f'{song_id}.mp3')
                if os.path.exists(audio_path):
                    duration = get_duration(audio_path)
                    bg_path = os.path.join(VIDEO_POSES, INST_BG)

                    still_path = os.path.join(VIDEO_SEGMENTS, f'{song_id}_still.mp4')
                    if not os.path.exists(still_path):
                        make_still_video(bg_path, duration, still_path)

                    merged_path = os.path.join(VIDEO_SEGMENTS, f'{song_id}_final.mp4')
                    if not os.path.exists(merged_path):
                        merge_video_audio(still_path, audio_path, merged_path)

                    title = SONG_TITLES.get(song_id, song_id)
                    add_segment(merged_path, f"☕ {title}")

            # 재착석
            return_src = os.path.join(VIDEO_CLIPS, 'break_return.mp4')
            return_norm = os.path.join(TEMP_DIR, 'norm_break_return.mp4')
            if os.path.exists(return_src) and not os.path.exists(return_norm):
                normalize_clip(return_src, return_norm)
            if os.path.exists(return_norm):
                add_segment(return_norm)

    # ─── STEP 4: 최종 합치기 (FFmpeg concat) ────────────────
    print(f"\n[STEP 4] 최종 합치기 ({len(segments)}개 세그먼트)...")

    # concat 파일 리스트 생성
    concat_list = os.path.join(TEMP_DIR, 'concat_list.txt')
    with open(concat_list, 'w') as f:
        for seg in segments:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    final_output = os.path.join(VIDEO_OUTPUT, 'yein_cafe_music_final.mp4')

    success = run_cmd([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', concat_list,
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '22',
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        final_output
    ], "Final rendering")

    # ─── STEP 5: 타임스탬프 생성 ─────────────────────────────
    print("\n[STEP 5] 유튜브 타임스탬프 생성...")
    ts_path = os.path.join(VIDEO_OUTPUT, 'timestamps.txt')
    with open(ts_path, 'w', encoding='utf-8') as f:
        f.write("🎵 Tracklist\n\n")
        for time_sec, label in timestamps:
            f.write(f"{format_timestamp(time_sec)} {label}\n")

    print(f"  타임스탬프 저장: {ts_path}")

    # ─── 완료 ────────────────────────────────────────────────
    if success and os.path.exists(final_output):
        final_dur = get_duration(final_output)
        final_size = os.path.getsize(final_output) / (1024*1024*1024)
        print(f"\n{'='*60}")
        print(f"  ✅ 완료!")
        print(f"  파일: {final_output}")
        print(f"  길이: {format_timestamp(final_dur)} ({final_dur/60:.0f}분)")
        print(f"  크기: {final_size:.1f}GB")
        print(f"  해상도: {W}x{H} @ {FPS}fps")
        print(f"  타임스탬프: {ts_path}")
        print(f"{'='*60}")
    else:
        print("\n❌ 렌더링 실패. 위 에러 메시지를 확인하세요.")


if __name__ == '__main__':
    if '--check' in sys.argv:
        check_sources()
    else:
        assemble()
