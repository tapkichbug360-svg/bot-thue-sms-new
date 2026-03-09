# ============================================
# RUN.PS1 - CHẠY BOT THUÊ SMS - KHÔNG MẤT WINDOW
# ============================================

# Giữ cửa sổ này luôn mở
$host.UI.RawUI.WindowTitle = "🤖 BOT THUÊ SMS CONTROL PANEL"

# Màu sắc
$C = @{
    Header = "Magenta"
    Info = "Cyan"
    Success = "Green"
    Warning = "Yellow"
    Error = "Red"
    Highlight = "White"
}

function Write-Color {
    param([string]$Text, [string]$Color)
    Write-Host $Text -ForegroundColor $C[$Color]
}

# Banner
Clear-Host
Write-Color "╔════════════════════════════════════════════════════════════╗" "Header"
Write-Color "║     🤖 BOT THUÊ SMS - CONTROL PANEL - KHÔNG MẤT WINDOW    ║" "Header"
Write-Color "╚════════════════════════════════════════════════════════════╝" "Header"

# ============================================
# KIỂM TRA MÔI TRƯỜNG
# ============================================
Write-Color "`n📦 KIỂM TRA MÔI TRƯỜNG..." "Info"

# Kiểm tra Python
try {
    $py = python --version 2>&1
    Write-Color "   ✅ $py" "Success"
} catch {
    Write-Color "   ❌ Python chưa cài!" "Error"
    Read-Host "`nNhấn Enter để thoát"
    exit
}

# Kiểm tra file .env
if (-not (Test-Path ".env")) {
    Write-Color "   ⚠️ Tạo file .env mới..." "Warning"
    @"
BOT_TOKEN=8561464326:AAG6NPFNvvFV0vFWQP1t8qUMo3WrjW5Un90
API_KEY=eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ6emxhbXp6MTEyMiIsImp0aSI6IjgwNTYwIiwiaWF0IjoxNzYxNjEyODAzLCJleHAiOjE4MjM4MjA4MDN9.4u-0IEkd2dgB6QtLEMlgp0KG55JwDDfMiNd98BQNzuJljOA9UTDymPsqnheIqGFM7WVGx94iV71tZasx62JIvw
BASE_URL=https://apisim.codesim.net
ADMIN_ID=5180190297
MB_ACCOUNT=666666291005
MB_NAME=NGUYEN THE LAM
MB_BIN=970422
SEPAY_TOKEN=VGSB0UMKLEWKLHGFOBYZ2T5YM1T4RXHYOG3FEHVR6EMRXZU48N2QROT7CACMJHQ7
RENDER_URL=http://localhost:8080
"@ | Out-File -FilePath ".env" -Encoding UTF8
    Write-Color "   ✅ Đã tạo .env" "Success"
} else {
    Write-Color "   ✅ File .env tồn tại" "Success"
}

# ============================================
# TẠO FILE CHẠY TÁCH BIỆT
# ============================================

# 1. Tạo file start_flask.bat
@"
@echo off
cd /d C:\bot_thue_sms_24h
title 🔵 FLASK API - PORT 8080
echo ========================================
echo    🔵 FLASK API - PORT 8080
echo ========================================
echo.
python main.py
if errorlevel 1 (
    echo.
    echo ❌ Lỗi! Nhấn phím bất kỳ để thoát...
    pause >nul
)
"@ | Out-File -FilePath "start_flask.bat" -Encoding ASCII

# 2. Tạo file start_bot.bat
@"
@echo off
cd /d C:\bot_thue_sms_24h
title 🤖 TELEGRAM BOT
echo ========================================
echo    🤖 TELEGRAM BOT
echo ========================================
echo.
python bot.py
if errorlevel 1 (
    echo.
    echo ❌ Lỗi! Nhấn phím bất kỳ để thoát...
    pause >nul
)
"@ | Out-File -FilePath "start_bot.bat" -Encoding ASCII

# 3. Tạo file start_daemon.bat
@"
@echo off
cd /d C:\bot_thue_sms_24h
title 🔄 DAEMON SYNC
echo ========================================
echo    🔄 DAEMON SYNC
echo ========================================
echo.
echo Chọn option 4 để chạy daemon tự động
python daemon.py
if errorlevel 1 (
    echo.
    echo ❌ Lỗi! Nhấn phím bất kỳ để thoát...
    pause >nul
)
"@ | Out-File -FilePath "start_daemon.bat" -Encoding ASCII

# 4. Tạo file start_dashboard.bat
@"
@echo off
cd /d C:\bot_thue_sms_24h
title 📊 DASHBOARD - PORT 5000
echo ========================================
echo    📊 DASHBOARD - PORT 5000
echo ========================================
echo.
echo Dashboard URL: http://localhost:5000
echo.
python dashboard.py
if errorlevel 1 (
    echo.
    echo ❌ Lỗi! Nhấn phím bất kỳ để thoát...
    pause >nul
)
"@ | Out-File -FilePath "start_dashboard.bat" -Encoding ASCII

# 5. Tạo file start_ngrok.bat (nếu có)
@"
@echo off
cd /d C:\bot_thue_sms_24h
title 🌐 NGROK
echo ========================================
echo    🌐 NGROK - WEBHOOK URL
echo ========================================
echo.
echo Đợi ngrok khởi động...
echo.
ngrok http 8080
if errorlevel 1 (
    echo.
    echo ❌ Ngrok chưa cài! Tải tại: https://ngrok.com
    pause
)
"@ | Out-File -FilePath "start_ngrok.bat" -Encoding ASCII

# 6. Tạo file stop_all.bat để dừng tất cả
@"
@echo off
echo ========================================
echo    🛑 DỪNG TẤT CẢ SERVICES
echo ========================================
echo.
taskkill /F /IM python.exe 2>nul
taskkill /F /IM ngrok.exe 2>nul
echo ✅ Đã dừng tất cả!
timeout /t 3 /nobreak >nul
"@ | Out-File -FilePath "stop_all.bat" -Encoding ASCII

Write-Color "`n✅ Đã tạo các file batch:" "Success"
Write-Color "   • start_flask.bat     - Flask API" "Info"
Write-Color "   • start_bot.bat       - Telegram Bot" "Info"
Write-Color "   • start_daemon.bat    - Daemon đồng bộ" "Info"
Write-Color "   • start_dashboard.bat - Dashboard" "Info"
Write-Color "   • start_ngrok.bat     - Ngrok (nếu cần)" "Info"
Write-Color "   • stop_all.bat        - Dừng tất cả" "Info"

# ============================================
# MENU CHÍNH
# ============================================
function Show-Menu {
    Write-Color "`n" "Info"
    Write-Color "╔════════════════════════════════════════════════════════════╗" "Header"
    Write-Color "║                      🎯 MENU ĐIỀU KHIỂN                    ║" "Header"
    Write-Color "╠════════════════════════════════════════════════════════════╣" "Header"
    Write-Color "║  [1] 🚀 CHẠY TẤT CẢ (4 cửa sổ)                            ║" "Header"
    Write-Color "║  [2] 🌐 CHẠY + NGROK (có SePay)                           ║" "Header"
    Write-Color "║  [3] 🔧 CHẠY TỪNG PHẦN                                    ║" "Header"
    Write-Color "║  [4] 📊 KIỂM TRA TRẠNG THÁI                               ║" "Header"
    Write-Color "║  [5] 🛑 DỪNG TẤT CẢ                                       ║" "Header"
    Write-Color "║  [0] ❌ THOÁT                                              ║" "Header"
    Write-Color "╚════════════════════════════════════════════════════════════╝" "Header"
}

function Show-SubMenu {
    Write-Color "`n📋 CHỌN SERVICE ĐỂ CHẠY:" "Info"
    Write-Color "   a) 🔵 Flask API" "Info"
    Write-Color "   b) 🤖 Telegram Bot" "Info"
    Write-Color "   c) 🔄 Daemon Sync" "Info"
    Write-Color "   d) 📊 Dashboard" "Info"
    Write-Color "   e) 🌐 Ngrok" "Info"
    Write-Color "   f) 🔙 Quay lại" "Info"
}

function Check-Status {
    Write-Color "`n📊 KIỂM TRA TRẠNG THÁI:" "Info"
    
    # Kiểm tra processes
    $py = Get-Process -Name python -ErrorAction SilentlyContinue
    if ($py) {
        Write-Color "   🐍 Python processes đang chạy:" "Success"
        foreach ($p in $py) {
            $cmd = ($p.CommandLine -split ' ')[-1]
            Write-Host "      • PID $($p.Id): $cmd" -ForegroundColor Gray
        }
    } else {
        Write-Color "   ⚠️ Không có Python process nào" "Warning"
    }
    
    # Kiểm tra ports
    $ports = @(8080, 5000, 4040)
    foreach ($port in $ports) {
        $conn = Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue
        if ($conn.TcpTestSucceeded) {
            switch ($port) {
                8080 { Write-Color "      ✅ Port 8080 (Flask API): ĐANG CHẠY" "Success" }
                5000 { Write-Color "      ✅ Port 5000 (Dashboard): ĐANG CHẠY" "Success" }
                4040 { Write-Color "      ✅ Port 4040 (ngrok API): ĐANG CHẠY" "Success" }
            }
        }
    }
    
    # Kiểm tra ngrok URL
    if (Get-Process -Name ngrok -ErrorAction SilentlyContinue) {
        try {
            $api = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -ErrorAction Stop
            $url = $api.tunnels[0].public_url
            Write-Color "   🌐 Ngrok URL: $url" "Highlight"
            Write-Color "   📌 Webhook SePay: $url/webhook/sepay" "Warning"
        } catch {
            Write-Color "   ⚠️ Ngrok đang chạy nhưng chưa có URL" "Warning"
        }
    }
}

# ============================================
# MAIN LOOP
# ============================================

do {
    Show-Menu
    $choice = Read-Host "`n👉 Chọn (0-5)"
    
    switch ($choice) {
        "1" {
            Write-Color "`n🚀 ĐANG MỞ TẤT CẢ SERVICES..." "Info"
            Start-Process -FilePath "start_flask.bat" -WindowStyle Normal
            Start-Sleep -Seconds 2
            Start-Process -FilePath "start_bot.bat" -WindowStyle Normal
            Start-Sleep -Seconds 2
            Start-Process -FilePath "start_daemon.bat" -WindowStyle Normal
            Start-Sleep -Seconds 2
            Start-Process -FilePath "start_dashboard.bat" -WindowStyle Normal
            Write-Color "✅ Đã mở 4 cửa sổ!" "Success"
            Write-Color "📌 Đừng đóng cửa sổ này!" "Warning"
            Read-Host "`nNhấn Enter để tiếp tục"
        }
        "2" {
            Write-Color "`n🚀 ĐANG MỞ TẤT CẢ + NGROK..." "Info"
            
            # Kiểm tra ngrok
            if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
                Write-Color "   ⚠️ Ngrok chưa cài!" "Warning"
                $dl = Read-Host "Tải ngrok ngay? (y/n)"
                if ($dl -eq 'y') {
                    Write-Color "   📥 Đang tải ngrok..." "Info"
                    $url = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
                    $zip = "$env:TEMP\ngrok.zip"
                    Invoke-WebRequest -Uri $url -OutFile $zip
                    Expand-Archive -Path $zip -DestinationPath "C:\ngrok" -Force
                    $env:Path += ";C:\ngrok"
                    Write-Color "   ✅ Đã cài ngrok tại C:\ngrok" "Success"
                }
            }
            
            # Mở các services
            Start-Process -FilePath "start_flask.bat" -WindowStyle Normal
            Start-Sleep -Seconds 2
            Start-Process -FilePath "start_bot.bat" -WindowStyle Normal
            Start-Sleep -Seconds 2
            Start-Process -FilePath "start_daemon.bat" -WindowStyle Normal
            Start-Sleep -Seconds 2
            Start-Process -FilePath "start_dashboard.bat" -WindowStyle Normal
            Start-Sleep -Seconds 3
            Start-Process -FilePath "start_ngrok.bat" -WindowStyle Normal
            
            Write-Color "✅ Đã mở 5 cửa sổ!" "Success"
            Write-Color "`n⏳ Đợi 5 giây để lấy URL ngrok..." "Info"
            Start-Sleep -Seconds 5
            
            # Lấy URL ngrok
            try {
                $api = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -ErrorAction Stop
                $url = $api.tunnels[0].public_url
                Write-Color "`n🌐 NGROK URL: $url" "Highlight"
                Write-Color "📌 Cập nhật SePay webhook: $url/webhook/sepay" "Warning"
                
                # Copy vào clipboard
                $url + "/webhook/sepay" | Set-Clipboard
                Write-Color "✅ Đã copy URL vào clipboard!" "Success"
            } catch {
                Write-Color "⚠️ Chưa lấy được URL, kiểm tra cửa sổ ngrok" "Warning"
            }
            
            Read-Host "`nNhấn Enter để tiếp tục"
        }
        "3" {
            do {
                Show-SubMenu
                $sub = Read-Host "`n👉 Chọn (a-f)"
                
                switch ($sub) {
                    "a" { Start-Process -FilePath "start_flask.bat" -WindowStyle Normal }
                    "b" { Start-Process -FilePath "start_bot.bat" -WindowStyle Normal }
                    "c" { Start-Process -FilePath "start_daemon.bat" -WindowStyle Normal }
                    "d" { Start-Process -FilePath "start_dashboard.bat" -WindowStyle Normal }
                    "e" { Start-Process -FilePath "start_ngrok.bat" -WindowStyle Normal }
                    "f" { break }
                    default { Write-Color "❌ Sai chọn!" "Error" }
                }
                if ($sub -ne "f") {
                    Write-Color "✅ Đã mở cửa sổ!" "Success"
                    Read-Host "Nhấn Enter để tiếp tục"
                }
            } while ($sub -ne "f")
        }
        "4" {
            Check-Status
            Read-Host "`nNhấn Enter để tiếp tục"
        }
        "5" {
            Write-Color "`n🛑 ĐANG DỪNG TẤT CẢ..." "Warning"
            .\stop_all.bat
            Write-Color "✅ Đã dừng!" "Success"
            Read-Host "`nNhấn Enter để tiếp tục"
        }
        "0" {
            Write-Color "`n👋 Tạm biệt!" "Success"
            exit
        }
        default {
            Write-Color "❌ Sai lựa chọn!" "Error"
            Read-Host "`nNhấn Enter để tiếp tục"
        }
    }
} while ($true)
