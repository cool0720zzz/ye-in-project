@echo off
chcp 65001 >nul
title 예인 ComfyUI (Intel Arc XPU)
echo ============================================
echo   예인 이미지 생성 - ComfyUI 시작 중...
echo   브라우저가 자동으로 열립니다 (localhost:8188)
echo   끄려면 이 검은 창을 닫으세요.
echo ============================================
cd /d C:\Users\coolk\ComfyUI
call C:\Users\coolk\comfy-xpu\Scripts\activate.bat
python main.py --port 8188 --auto-launch
pause
