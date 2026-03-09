@echo off
cd /d C:\bot_thue_sms_24h
title ?? DASHBOARD - PORT 5000
echo ========================================
echo    ?? DASHBOARD - PORT 5000
echo ========================================
echo.
echo Dashboard URL: http://localhost:5000
echo.
python dashboard.py
if errorlevel 1 (
    echo.
    echo ? L?i! Nh?n ph?m b?t k? ?? tho?t...
    pause >nul
)
