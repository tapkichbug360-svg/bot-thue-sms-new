@echo off
cd /d C:\bot_thue_sms_24h
title ?? TELEGRAM BOT
echo ========================================
echo    ?? TELEGRAM BOT
echo ========================================
echo.
python bot.py
if errorlevel 1 (
    echo.
    echo ? L?i! Nh?n ph?m b?t k? ?? tho?t...
    pause >nul
)
