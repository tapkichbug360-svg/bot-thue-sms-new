@echo off
cd /d C:\bot_thue_sms_24h
title ?? DAEMON SYNC
echo ========================================
echo    ?? DAEMON SYNC
echo ========================================
echo.
echo Ch?n option 4 ?? ch?y daemon t? ??ng
python daemon.py
if errorlevel 1 (
    echo.
    echo ? L?i! Nh?n ph?m b?t k? ?? tho?t...
    pause >nul
)
