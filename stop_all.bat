@echo off
echo ========================================
echo    ?? D?NG T?T C? SERVICES
echo ========================================
echo.
taskkill /F /IM python.exe 2>nul
taskkill /F /IM ngrok.exe 2>nul
echo ? ?? d?ng t?t c?!
timeout /t 3 /nobreak >nul
