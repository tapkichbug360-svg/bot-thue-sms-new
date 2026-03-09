@echo off
cd /d C:\bot_thue_sms_24h
title ?? NGROK
echo ========================================
echo    ?? NGROK - WEBHOOK URL
echo ========================================
echo.
echo ??i ngrok kh?i ??ng...
echo.
ngrok http 8080
if errorlevel 1 (
    echo.
    echo ? Ngrok ch?a c?i! T?i t?i: https://ngrok.com
    pause
)
