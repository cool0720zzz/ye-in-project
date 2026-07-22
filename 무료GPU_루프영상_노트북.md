# 무료 GPU로 루프 영상 만들기 — Kaggle 노트북

> 목적: **워터마크 없이, 상업 이용 가능한 루프 영상을 $0로** 만들기
> 환경: Kaggle Notebook + 무료 T4 GPU (15GB)
> 모델: LTX-Video (I2V — 예인 스틸을 첫 프레임으로)

## 시작 전 설정 (반드시)

Kaggle 노트북 우측 패널에서:
1. **Accelerator → GPU T4 x2** (또는 P100)
2. **Internet → On** ← 안 켜면 모델 다운로드 실패
3. 셀 실행 전 **Run → Restart & Clear Cell Outputs** (메모리 파편화 방지)

---

## Cell 1 — 환경변수 + 설치

⚠️ `PYTORCH_CUDA_ALLOC_CONF`는 **torch를 import하기 전에** 설정돼야 효과가 있다.

```python
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

!pip install -q -U diffusers transformers accelerate sentencepiece imageio imageio-ffmpeg
print("설치 완료")
```

---

## Cell 2 — 모델 로드 (메모리 대책 전부 적용)

```python
import torch, gc
from diffusers import LTXImageToVideoPipeline

def vram(tag=""):
    a = torch.cuda.memory_allocated()/1024**3
    r = torch.cuda.memory_reserved()/1024**3
    t = torch.cuda.get_device_properties(0).total_memory/1024**3
    print(f"[{tag}] 할당 {a:.2f}GB / 예약 {r:.2f}GB / 전체 {t:.2f}GB")

def clean():
    gc.collect(); torch.cuda.empty_cache()

clean(); vram("시작")

pipe = LTXImageToVideoPipeline.from_pretrained(
    "Lightricks/LTX-Video",
    torch_dtype=torch.float16,      # T4는 bfloat16이 느림 → float16
)

# ★ 메모리 대책 (순서 중요)
pipe.enable_model_cpu_offload()     # 안 쓰는 모듈은 CPU로 — 효과 가장 큼
pipe.vae.enable_tiling()            # ★ VAE 디코드를 타일로 쪼갬 (OOM 주범)
pipe.vae.enable_slicing()
try:
    pipe.enable_attention_slicing()
except Exception:
    pass

clean(); vram("모델 로드 후")
print("준비 완료")
```

> ⚠️ `enable_model_cpu_offload()`를 쓰면 **`pipe.to("cuda")`를 호출하면 안 된다.** 충돌한다.

---

## Cell 3 — 앵커 이미지 준비

예인 스틸을 첫 프레임으로 쓴다. 노트북 우측 **Input → Upload**로 올린 뒤 경로를 맞춘다.

```python
import glob
from PIL import Image

print(glob.glob("/kaggle/input/**/*.*", recursive=True)[:20])
```

```python
IMG_PATH = "/kaggle/input/여기에-업로드한-폴더명/예인.png"   # ← 위 목록에서 복사

# LTX는 가로·세로가 32의 배수여야 한다. T4에서는 512x320이 안전
W, H = 512, 320

img = Image.open(IMG_PATH).convert("RGB")
# 비율 유지 센터 크롭 후 리사이즈
r = W / H
w, h = img.size
if w / h > r:
    nw = int(h * r); img = img.crop(((w - nw)//2, 0, (w - nw)//2 + nw, h))
else:
    nh = int(w / r); img = img.crop((0, (h - nh)//2, w, (h - nh)//2 + nh))
img = img.resize((W, H), Image.LANCZOS)
img
```

---

## Cell 4 — 생성

```python
PROMPT = (
    "Seamless loop. She sits still, gazing calmly out the window. "
    "Only subtle ambient motion: soft light flickers across her face, "
    "faint breathing, tiny dust drifting in the light. "
    "Head and body stay steady. Static locked camera, fixed framing."
)
NEG = "camera movement, zoom, pan, jitter, morphing, distorted face, extra limbs, text, watermark"

clean(); vram("생성 전")

out = pipe(
    image=img,
    prompt=PROMPT,
    negative_prompt=NEG,
    width=W, height=H,
    num_frames=65,              # 8n+1 규칙. 65 ≈ 2.7초(24fps)
    num_inference_steps=30,
    guidance_scale=3.0,
    generator=torch.Generator().manual_seed(1234),
)
frames = out.frames[0]

clean(); vram("생성 후")
print(f"프레임 {len(frames)}장")
```

---

## Cell 5 — 루프로 만들어 저장

LTX는 네이티브 루프 기능이 없다. **가장 잘 맞물리는 두 프레임을 찾아** 그 구간만 잘라 하드 루프로 만든다.

```python
import numpy as np, imageio

# ⚠️ 축소 폭 192 / 샘플링 간격 7은 프로젝트의 scripts/find_loop.py와 동일하게 맞춘 값.
#    바꾸면 dB 수치가 달라져 기존 측정과 비교가 안 된다.
SW = 192
sh = int(frames[0].height * SW / frames[0].width)
arr = np.stack([np.asarray(f.convert("L").resize((SW, sh)), dtype=np.float32) for f in frames])
flat = arr.reshape(len(arr), -1)
sq = (flat**2).sum(1)
d2 = np.maximum(sq[:,None] + sq[None,:] - 2*(flat @ flat.T), 0)
mse = d2 / flat.shape[1]
psnr = 10*np.log10(255.0**2 / np.maximum(mse, 1e-9))

MIN_GAP = 24                      # 최소 1초(24fps)
ii, jj = np.indices(psnr.shape)
psnr[(jj - ii) < MIN_GAP] = -1
i, j = np.unravel_index(np.argmax(psnr), psnr.shape)

# 인접 프레임 노이즈 바닥선 대비 판정
adj = np.median([10*np.log10(255.0**2/max(np.mean((arr[k]-arr[k+1])**2),1e-9))
                 for k in range(0, len(arr)-1, 7)])
gap = adj - psnr[i, j]
verdict = ("사실상 동일" if gap <= 1.5 else "거의 안 보임" if gap <= 4
           else "자세히 보면 보임" if gap <= 7 else "명확히 튐 — 재생성 권장")

print(f"루프 구간 {i}~{j} ({(j-i)/24:.2f}초)  PSNR {psnr[i,j]:.2f}dB  바닥선 {adj:.2f}dB")
print(f"판정: {verdict}")

imageio.mimsave("/kaggle/working/loop.mp4", [np.asarray(f) for f in frames[i:j]],
                fps=24, codec="libx264", quality=8)
print("저장 완료 → 우측 Output 패널에서 loop.mp4 다운로드")
```

---

## OOM이 또 나면 — 이 순서로

| 순서 | 조치 | 효과 |
|---|---|---|
| 1 | **커널 재시작** 후 재실행 | 파편화 해소 |
| 2 | `num_frames` 65 → **49** | 큼 |
| 3 | `W, H` 512×320 → **384×256** | **가장 큼** |
| 4 | `num_inference_steps` 30 → 20 | 속도만 |
| 5 | `pipe.enable_sequential_cpu_offload()`로 교체 | 매우 큼(대신 느림) |

> 💡 **해상도가 메모리에 가장 크게 영향을 준다.** 프레임 수보다 먼저 해상도를 내릴 것.
> 💡 스텝이 다 끝난 뒤(30/30) 터지면 **VAE 디코드**가 원인 — `vae.enable_tiling()`이 빠졌는지 확인.

## 라이선스 메모
- **LTX-Video**: Lightricks 공개 가중치. 상업 이용 조건은 배포처에서 확인할 것
- **완전한 상업 자유(Apache 2.0)를 원하면** Wan 2.1 계열이 안전하나, I2V 모델은 14B라 T4에 안 올라간다
  (T2V 1.3B는 올라가지만 앵커 이미지를 못 씀 → 예인 얼굴 일관성 상실)
- 워터마크는 **어느 쪽이든 없다** (로컬/자체 GPU 생성이므로)

## 이 방식의 한계
- 네이티브 루프가 없어 **후처리로 구간을 잘라내는 방식** → 루마의 Loop 기능보다 성공률이 낮다
- 판정이 "명확히 튐"이면 시드를 바꿔 재생성. 앰비언트(정지에 가까운) 모션일수록 성공률이 올라간다
