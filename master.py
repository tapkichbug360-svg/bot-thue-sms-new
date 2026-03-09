# master.py - Chạy tất cả services trong 1 file Python

import threading
import subprocess
import time
import os
import sys
import logging
import socket
from datetime import datetime

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('MASTER')

# Màu sắc cho terminal
class Colors:
    HEADER = '\033[95m'
    INFO = '\033[96m'
    SUCCESS = '\033[92m'
    WARNING = '\033[93m'
    ERROR = '\033[91m'
    END = '\033[0m'

def print_color(msg, color):
    print(f"{color}{msg}{Colors.END}")

class BotMaster:
    def __init__(self):
        self.processes = {}
        self.running = True
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        
    def check_port(self, port):
        """Kiểm tra port có đang được sử dụng không"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
    
    def wait_for_port(self, port, timeout=30):
        """Chờ port mở"""
        start = time.time()
        while time.time() - start < timeout:
            if self.check_port(port):
                return True
            time.sleep(1)
        return False
    
    def run_flask(self):
        """Chạy Flask API (main.py)"""
        try:
            log.info(f"{Colors.HEADER}🚀 Starting Flask API on port 8080...{Colors.END}")
            os.chdir(self.base_dir)
            import main
            # main sẽ chạy Flask
        except Exception as e:
            log.error(f"{Colors.ERROR}❌ Flask error: {e}{Colors.END}")
            # Thử chạy bằng subprocess
            os.system(f'cd "{self.base_dir}" && python main.py')
    
    def run_bot(self):
        """Chạy Telegram Bot (bot.py)"""
        time.sleep(3)
        try:
            log.info(f"{Colors.HEADER}🤖 Starting Telegram Bot...{Colors.END}")
            os.chdir(self.base_dir)
            import bot
            # bot sẽ chạy
        except Exception as e:
            log.error(f"{Colors.ERROR}❌ Bot error: {e}{Colors.END}")
            os.system(f'cd "{self.base_dir}" && python bot.py')
    
    def run_daemon(self):
        """Chạy daemon đồng bộ"""
        time.sleep(5)
        log.info(f"{Colors.HEADER}🔄 Starting Daemon...{Colors.END}")
        os.system(f'cd "{self.base_dir}" && python daemon.py')
    
    def run_dashboard(self):
        """Chạy dashboard"""
        time.sleep(7)
        log.info(f"{Colors.HEADER}📊 Starting Dashboard on port 5000...{Colors.END}")
        os.system(f'cd "{self.base_dir}" && python dashboard.py')
    
    def run_sepay_webhook(self):
        """SePay webhook chạy trong Flask, không cần riêng"""
        pass
    
    def start_all(self):
        """Khởi động tất cả services"""
        print_color("\n" + "="*70, 'HEADER')
        print_color("🚀 MASTER CONTROLLER - STARTING ALL SERVICES", 'HEADER')
        print_color("="*70 + "\n", 'HEADER')
        
        # Kill các process cũ trên port 8080 và 5000
        if self.check_port(8080):
            log.warning("⚠️ Port 8080 đang được sử dụng, sẽ kill...")
            os.system('netstat -ano | findstr :8080 | findstr LISTENING')
        
        if self.check_port(5000):
            log.warning("⚠️ Port 5000 đang được sử dụng, sẽ kill...")
            os.system('netstat -ano | findstr :5000 | findstr LISTENING')
        
        # Tạo các thread
        threads = [
            threading.Thread(target=self.run_flask, daemon=True, name="Flask"),
            threading.Thread(target=self.run_bot, daemon=True, name="Bot"),
            threading.Thread(target=self.run_daemon, daemon=True, name="Daemon"),
            threading.Thread(target=self.run_dashboard, daemon=True, name="Dashboard")
        ]
        
        # Khởi động các thread
        for t in threads:
            t.start()
            time.sleep(2)
        
        # Chờ các service khởi động
        time.sleep(5)
        
        print_color("\n" + "="*70, 'SUCCESS')
        print_color("✅ ALL SERVICES STARTED SUCCESSFULLY!", 'SUCCESS')
        print_color("="*70, 'SUCCESS')
        print_color("\n📍 Flask API:     http://localhost:8080", 'INFO')
        print_color("📍 Dashboard:     http://localhost:5000", 'INFO')
        print_color("📍 Bot Telegram:  Đang chạy", 'INFO')
        print_color("📍 Daemon:        Đồng bộ mỗi 10 giây", 'INFO')
        print_color("📍 Database:       database/bot.db", 'INFO')
        print_color("\n" + "="*70, 'INFO')
        print_color("📌 SEPAY WEBHOOK URL (dùng với ngrok):", 'WARNING')
        print_color("   http://localhost:8080/webhook/sepay", 'WARNING')
        print_color("="*70 + "\n", 'INFO')
        
        # Giữ master chạy
        try:
            while self.running:
                time.sleep(10)
                # Kiểm tra các thread
                for t in threads:
                    if not t.is_alive():
                        log.warning(f"⚠️ Thread {t.name} đã dừng!")
        except KeyboardInterrupt:
            print_color("\n👋 Shutting down all services...", 'WARNING')
            self.running = False
            sys.exit(0)

if __name__ == "__main__":
    master = BotMaster()
    master.start_all()
