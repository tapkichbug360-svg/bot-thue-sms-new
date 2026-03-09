@echo off
cd /d C:\bot_thue_sms_24h
title ?? FLASK API - PORT 8080
echo ========================================
echo    ?? FLASK API - PORT 8080
echo ========================================
echo.
python main.py
if errorlevel 1 (
    echo.
    echo ? L?i! Nh?n ph?m b?t k? ?? tho?t...
    pause >nul
)
