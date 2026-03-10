import sqlite3
import requests
import time
import os
import json
from datetime import datetime, timedelta, timezone
import concurrent.futures
import threading
from collections import defaultdict
import psutil

# ==================== CẤU HÌNH ====================
VN_TZ = timezone(timedelta(hours=7))
RENDER_URL = "https://bot-thue-sms-new.onrender.com"
BOT_TOKEN = os.getenv('BOT_TOKEN', '8561464326:AAG6NPFNvvFV0vFWQP1t8qUMo3WrjW5Un90')

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

# ==================== CLASS CHÍNH ====================
class UserSyncDaemon:
    def __init__(self):
        self.running = True
        self.last_sync = {}
        self.failed_pushes_file = "failed_pushes.json"
        self.db_path = os.path.join('database', 'bot.db')
        
        # ===== THAM SỐ TỐI ƯU =====
        self.batch_size = 50           # Số user mỗi batch
        self.batch_delay = 1           # Nghỉ 1s giữa các batch
        self.max_workers = 10           # Số luồng xử lý song song
        self.push_timeout = 5           # Timeout push (giây)
        self.pull_timeout = 10          # Timeout pull (giây)
        self.retry_limit = 2            # Số lần thử lại
        self.stats_interval = 300       # In stats mỗi 5 phút
        
        # ===== THEO DÕI HIỆU SUẤT =====
        self.stats = {
            'total_processed': 0,
            'push_success': 0,
            'push_failed': 0,
            'pull_success': 0,
            'pull_failed': 0,
            'total_time': 0,
            'avg_response': 0,
            'errors': defaultdict(int)
        }
        self.stats_lock = threading.Lock()
    
    # ==================== HÀM TIỆN ÍCH ====================
    def get_db_connection(self):
        """Tạo kết nối database"""
        return sqlite3.connect(self.db_path)
    
    def log(self, message, level="INFO"):
        """Ghi log có màu sắc"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        colors = {
            "INFO": "\033[96m",     # Cyan
            "SUCCESS": "\033[92m",  # Xanh lá
            "WARNING": "\033[93m",  # Vàng
            "ERROR": "\033[91m",    # Đỏ
            "PERF": "\033[95m",     # Tím (performance)
            "RESET": "\033[0m"
        }
        color = colors.get(level, colors["INFO"])
        print(f"{color}[{timestamp}] {message}{colors['RESET']}")
    
    def update_stats(self, key, value=1):
        """Cập nhật thống kê an toàn luồng"""
        with self.stats_lock:
            if key in self.stats:
                self.stats[key] += value
            else:
                self.stats[key] = value
    
    def print_stats(self):
        """In thống kê hiệu suất"""
        self.log("\n" + "="*70, "PERF")
        self.log("📊 PERFORMANCE STATISTICS", "PERF")
        self.log("="*70, "PERF")
        self.log(f"• Total processed: {self.stats['total_processed']}", "PERF")
        self.log(f"• Push success: {self.stats['push_success']}", "SUCCESS")
        self.log(f"• Push failed: {self.stats['push_failed']}", "ERROR")
        self.log(f"• Pull success: {self.stats['pull_success']}", "SUCCESS")
        self.log(f"• Pull failed: {self.stats['pull_failed']}", "ERROR")
        self.log(f"• Avg response: {self.stats['avg_response']:.2f}s", "PERF")
        self.log(f"• Memory: {psutil.Process().memory_percent():.1f}%", "PERF")
        self.log(f"• CPU: {psutil.Process().cpu_percent():.1f}%", "PERF")
        
        if self.stats['errors']:
            self.log("\n⚠️ TOP ERRORS:", "WARNING")
            for error, count in sorted(self.stats['errors'].items(), key=lambda x: x[1], reverse=True)[:5]:
                self.log(f"   • {error}: {count}", "WARNING")
        self.log("="*70, "PERF")
    
    # ==================== LẤY DỮ LIỆU TỪ LOCAL ====================
    def get_all_local_users(self):
        """Lấy tất cả user từ database local"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, username, balance FROM users')
            users = cursor.fetchall()
            conn.close()
            
            result = []
            for row in users:
                result.append({
                    'user_id': row[0],
                    'username': row[1] if row[1] else f"user_{row[0]}",
                    'balance': row[2]
                })
            
            self.log(f"📋 Local có {len(result)} user", "INFO")
            return result
        except Exception as e:
            self.log(f"❌ Lỗi lấy user local: {e}", "ERROR")
            self.update_stats('errors', f"DB_ERROR: {str(e)[:50]}")
            return []
    
    def get_user_balance(self, user_id):
        """Lấy số dư user từ local"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else 0
        except Exception as e:
            self.log(f"❌ Lỗi lấy balance user {user_id}: {e}", "ERROR")
            return 0
    
    def update_local_balance(self, user_id, new_balance):
        """Cập nhật số dư trong local database"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.log(f"❌ Lỗi cập nhật local user {user_id}: {e}", "ERROR")
            return False
    
    def get_pending_transactions(self, limit=50):
        """Lấy các transaction đang chờ xử lý (có giới hạn)"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    SELECT transaction_id, amount, user_id, status
                    FROM deposit_transactions 
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT ?
                """, (limit,))
                pending = cursor.fetchall()
                
                result = []
                for trans_id, amount, user_id, status in pending:
                    cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                    user = cursor.fetchone()
                    username = user[0] if user else f"user_{user_id}"
                    
                    result.append({
                        'code': trans_id,
                        'amount': amount,
                        'user_id': user_id,
                        'username': username,
                        'status': status
                    })
                
                conn.close()
                return result
            except sqlite3.OperationalError:
                pass
            
            conn.close()
            return []
        except Exception as e:
            self.log(f"❌ Lỗi lấy transaction: {e}", "ERROR")
            return []
    
    def get_active_users(self, minutes=60):
        """Lấy user có hoạt động trong khoảng thời gian"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            
            # User có rental gần đây
            cursor.execute("""
                SELECT DISTINCT user_id FROM rentals 
                WHERE created_at > ? OR refunded_at > ?
            """, (time_threshold, time_threshold))
            
            active_ids = set([row[0] for row in cursor.fetchall()])
            
            # User có transaction gần đây
            cursor.execute("""
                SELECT DISTINCT user_id FROM deposit_transactions 
                WHERE created_at > ?
            """, (time_threshold,))
            
            active_ids.update([row[0] for row in cursor.fetchall()])
            
            conn.close()
            
            # Lấy thông tin đầy đủ
            all_users = self.get_all_local_users()
            active_users = [u for u in all_users if u['user_id'] in active_ids]
            
            self.log(f"⚡ Active users ({minutes}ph): {len(active_users)}/{len(all_users)}", "INFO")
            return active_users, [u for u in all_users if u['user_id'] not in active_ids]
            
        except Exception as e:
            self.log(f"❌ Lỗi lấy active users: {e}", "ERROR")
            return [], self.get_all_local_users()
    
    # ==================== GỬI THÔNG BÁO TELEGRAM ====================
    def send_telegram_notification(self, user_id, new_balance, amount, type="NAP"):
        """Gửi thông báo Telegram - KHÔNG BLOCK"""
        try:
            current_time = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
            
            if type == "NAP":
                message = (
                    f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                    f"• **Số tiền:** +{amount:,}đ\n"
                    f"• **Số dư mới:** {new_balance:,}đ\n"
                    f"• **Thời gian:** {current_time}"
                )
            else:
                message = (
                    f"💸 **CẬP NHẬT SỐ DƯ**\n\n"
                    f"• **Biến động:** {amount:+,}đ\n"
                    f"• **Số dư mới:** {new_balance:,}đ\n"
                    f"• **Thời gian:** {current_time}"
                )
            
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': user_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            # Timeout 10s
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                self.log(f"📨 Đã gửi Telegram cho user {user_id}", "SUCCESS")
            else:
                self.log(f"⚠️ Telegram lỗi {response.status_code}", "WARNING")
                
        except requests.exceptions.Timeout:
            self.log(f"⏰ Telegram timeout", "WARNING")
        except Exception as e:
            self.log(f"⚠️ Telegram lỗi: {e}", "WARNING")
    
    # ==================== ĐẨY DỮ LIỆU LÊN RENDER ====================
    def push_user_to_render(self, user_id, balance, username, reason=""):
        """Đẩy user lên Render - CÓ ĐO THỜI GIAN"""
        start_time = time.time()
        
        for attempt in range(self.retry_limit):
            try:
                response = requests.post(
                    f"{RENDER_URL}/api/sync-bidirectional",
                    json={
                        'user_id': user_id,
                        'balance': balance,
                        'username': username
                    },
                    timeout=self.push_timeout
                )
                
                elapsed = time.time() - start_time
                self.update_stats('total_processed')
                self.update_stats('avg_response', (elapsed - self.stats['avg_response']) / (self.stats['total_processed'] + 1))
                
                if response.status_code == 200:
                    self.update_stats('push_success')
                    return True
                else:
                    self.log(f"⚠️ Push user {user_id} lỗi {response.status_code}", "WARNING")
                    
            except Exception as e:
                self.log(f"⚠️ Lần {attempt + 1} lỗi: {e}", "WARNING")
                if attempt < self.retry_limit - 1:
                    time.sleep(2 ** attempt)
        
        self.update_stats('push_failed')
        self._save_failed_push(user_id, balance, username, reason)
        return False
    
    def push_user_batch(self, users):
        """Đẩy nhiều user song song"""
        success = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for user in users:
                future = executor.submit(
                    self.push_user_to_render,
                    user['user_id'],
                    user['balance'],
                    user['username']
                )
                futures.append(future)
            
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    success += 1
        
        return success
    
    # ==================== KÉO DỮ LIỆU TỪ RENDER VỀ ====================
    def pull_user_from_render(self, user_id):
        """Kéo user từ Render về - CÓ ĐO THỜI GIAN"""
        start_time = time.time()
        
        try:
            response = requests.post(
                f"{RENDER_URL}/api/force-sync-user",
                json={'user_id': user_id},
                timeout=self.pull_timeout
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                render_balance = data.get('balance')
                
                if render_balance is not None:
                    local_balance = self.get_user_balance(user_id)
                    
                    if render_balance != local_balance:
                        self.update_local_balance(user_id, render_balance)
                        diff = render_balance - local_balance
                        self.log(f"✅ User {user_id}: {local_balance}đ → {render_balance}đ ({diff:+,}đ)", "SUCCESS")
                        
                        # Gửi Telegram không block
                        threading.Thread(
                            target=self.send_telegram_notification,
                            args=(user_id, render_balance, diff, "NAP" if diff > 0 else "TIÊU")
                        ).start()
                    
                    self.update_stats('pull_success')
                    return True
            else:
                self.log(f"⚠️ Pull user {user_id} lỗi {response.status_code}", "WARNING")
                self.update_stats('pull_failed')
                
        except Exception as e:
            self.log(f"❌ Lỗi pull user {user_id}: {e}", "ERROR")
            self.update_stats('pull_failed')
            self.update_stats('errors', f"PULL_ERROR: {str(e)[:50]}")
        
        return False
    
    def pull_user_batch(self, users):
        """Kéo nhiều user song song"""
        success = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for user in users:
                future = executor.submit(self.pull_user_from_render, user['user_id'])
                futures.append(future)
            
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    success += 1
        
        return success
    
    # ==================== XỬ LÝ FAILED PUSHES ====================
    def _save_failed_push(self, user_id, balance, username, reason):
        """Lưu push thất bại"""
        try:
            failed = []
            if os.path.exists(self.failed_pushes_file):
                with open(self.failed_pushes_file, 'r') as f:
                    failed = json.load(f)
            
            failed.append({
                'user_id': user_id,
                'balance': balance,
                'username': username,
                'reason': reason,
                'time': datetime.now().isoformat()
            })
            
            # Giới hạn 200 entry
            if len(failed) > 200:
                failed = failed[-200:]
            
            with open(self.failed_pushes_file, 'w') as f:
                json.dump(failed, f, indent=2)
            
            self.log(f"💾 Đã lưu push thất bại user {user_id}", "WARNING")
        except Exception as e:
            self.log(f"❌ Lỗi lưu failed push: {e}", "ERROR")
    
    def retry_failed_pushes(self):
        """Thử lại các push thất bại"""
        try:
            if not os.path.exists(self.failed_pushes_file):
                return
            
            with open(self.failed_pushes_file, 'r') as f:
                failed = json.load(f)
            
            if not failed:
                return
            
            self.log(f"🔄 Thử lại {len(failed)} push thất bại...", "INFO")
            
            # Thử lại theo batch
            success = []
            remaining = []
            
            for i in range(0, len(failed), self.batch_size):
                batch = failed[i:i+self.batch_size]
                batch_success = 0
                
                for item in batch:
                    if self.push_user_to_render(
                        item['user_id'], 
                        item['balance'], 
                        item['username'], 
                        item.get('reason', 'retry')
                    ):
                        batch_success += 1
                        success.append(item)
                    else:
                        remaining.append(item)
                    time.sleep(0.1)
                
                self.log(f"   Batch {i//self.batch_size + 1}: {batch_success}/{len(batch)} OK", "INFO")
                time.sleep(self.batch_delay)
            
            # Lưu lại những cái vẫn thất bại
            with open(self.failed_pushes_file, 'w') as f:
                json.dump(remaining, f, indent=2)
            
            self.log(f"✅ Thử lại thành công: {len(success)}", "SUCCESS")
            self.log(f"⏳ Còn lại: {len(remaining)}", "INFO")
            
        except Exception as e:
            self.log(f"❌ Lỗi retry: {e}", "ERROR")
    
    # ==================== ĐỒNG BỘ TRANSACTIONS ====================
    def push_transaction_to_render(self, transaction):
        """Đẩy transaction lên Render"""
        try:
            payload = {
                'transactions': [{
                    'code': transaction['code'],
                    'amount': transaction['amount'],
                    'user_id': transaction['user_id'],
                    'username': transaction['username'],
                    'created_at': datetime.now().isoformat()
                }]
            }
            
            response = requests.post(
                f"{RENDER_URL}/api/sync-pending",
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                self._update_transaction_status(transaction['code'], 'synced')
                return True
            
        except Exception as e:
            self.log(f"❌ Lỗi push transaction: {e}", "ERROR")
        
        return False
    
    def _update_transaction_status(self, transaction_code, status):
        """Cập nhật trạng thái transaction"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE deposit_transactions SET status = ? WHERE transaction_id = ?",
                (status, transaction_code)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self.log(f"❌ Lỗi cập nhật transaction: {e}", "ERROR")
    
    # ==================== ĐỒNG BỘ USER CỤ THỂ ====================
    def sync_user(self, user_id):
        """Đồng bộ một user cụ thể"""
        self.log(f"🔄 Đồng bộ user {user_id}...", "INFO")
        
        balance = self.get_user_balance(user_id)
        username = f"user_{user_id}"
        
        push_success = self.push_user_to_render(user_id, balance, username, "sync_single")
        pull_success = self.pull_user_from_render(user_id)
        
        if push_success and pull_success:
            self.log(f"✅ Đồng bộ user {user_id} thành công", "SUCCESS")
        else:
            self.log(f"⚠️ Đồng bộ user {user_id} chưa hoàn chỉnh", "WARNING")
        
        return push_success and pull_success
    
    # ==================== DAEMON CHẠY NỀN (TỐI ƯU) ====================
    def run_daemon_optimized(self, interval=60, mode="auto"):
        """
        Daemon tối ưu cho nhiều user
        
        Args:
            interval: Thời gian giữa các cycle (giây)
            mode: "auto" - tự động phân loại, "active" - chỉ active, "full" - tất cả
        """
        cycle_count = 0
        last_stats_time = time.time()
        
        self.log("="*70, "INFO")
        self.log(f"🚀 DAEMON SIÊU TỐI ƯU - {interval} GIÂY/LẦN", "INFO")
        self.log(f"   • Batch size: {self.batch_size}", "INFO")
        self.log(f"   • Workers: {self.max_workers}", "INFO")
        self.log(f"   • Mode: {mode}", "INFO")
        self.log("="*70, "INFO")
        
        while self.running:
            try:
                cycle_count += 1
                start_cycle = time.time()
                vn_time = get_vn_time()
                
                self.log(f"\n{'='*70}", "INFO")
                self.log(f"🔄 CYCLE #{cycle_count} - {vn_time.strftime('%H:%M:%S %d/%m/%Y')}", "INFO")
                
                # === THỬ LẠI PUSH THẤT BẠI ===
                self.retry_failed_pushes()
                
                # === LẤY USER THEO MODE ===
                if mode == "full":
                    all_users = self.get_all_local_users()
                    active_users = all_users
                    inactive_users = []
                else:
                    active_users, inactive_users = self.get_active_users(minutes=60)
                
                # === XỬ LÝ USER ACTIVE ===
                if active_users:
                    self.log(f"\n⚡ XỬ LÝ {len(active_users)} USER ACTIVE:", "INFO")
                    
                    # Chia batch
                    for i in range(0, len(active_users), self.batch_size):
                        batch = active_users[i:i+self.batch_size]
                        self.log(f"   Batch {i//self.batch_size + 1}: {len(batch)} users", "INFO")
                        
                        # Push song song
                        push_ok = self.push_user_batch(batch)
                        self.log(f"      Push: {push_ok}/{len(batch)}", "INFO")
                        
                        # Pull song song
                        pull_ok = self.pull_user_batch(batch)
                        self.log(f"      Pull: {pull_ok}/{len(batch)}", "INFO")
                        
                        time.sleep(self.batch_delay)
                
                # === XỬ LÝ USER INACTIVE (CHỈ PULL) ===
                if inactive_users and mode != "active":
                    self.log(f"\n💤 XỬ LÝ {len(inactive_users)} USER INACTIVE:", "INFO")
                    
                    for i in range(0, len(inactive_users), self.batch_size * 2):
                        batch = inactive_users[i:i+self.batch_size*2]
                        pull_ok = self.pull_user_batch(batch)
                        self.log(f"   Batch {i//(self.batch_size*2) + 1}: Pull {pull_ok}/{len(batch)}", "INFO")
                        time.sleep(self.batch_delay)
                
                # === ĐỒNG BỘ TRANSACTIONS ===
                transactions = self.get_pending_transactions(limit=50)
                if transactions:
                    self.log(f"\n💳 ĐỒNG BỘ {len(transactions)} TRANSACTIONS:", "INFO")
                    for trans in transactions:
                        if self.push_transaction_to_render(trans):
                            self.log(f"   ✅ {trans['code']}", "SUCCESS")
                        time.sleep(0.1)
                
                # === THỐNG KÊ ===
                elapsed = time.time() - start_cycle
                self.log(f"\n📊 CYCLE #{cycle_count} HOÀN TẤT:", "INFO")
                self.log(f"   • Thời gian: {elapsed:.1f}s", "INFO")
                self.log(f"   • Push success: {self.stats['push_success']}", "SUCCESS")
                self.log(f"   • Pull success: {self.stats['pull_success']}", "SUCCESS")
                
                # In stats định kỳ
                if time.time() - last_stats_time > self.stats_interval:
                    self.print_stats()
                    last_stats_time = time.time()
                
                # === CHỜ ===
                wait_time = max(1, interval - elapsed)
                self.log(f"\n⏳ Chờ {wait_time:.1f}s...", "INFO")
                
                for i in range(int(wait_time)):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except KeyboardInterrupt:
                self.log("\n👋 Đã dừng daemon", "INFO")
                self.print_stats()
                self.running = False
                break
            except Exception as e:
                self.log(f"❌ Lỗi daemon: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                time.sleep(10)
    
    def stop(self):
        """Dừng daemon"""
        self.running = False
        self.print_stats()
        self.log("🛑 Đã dừng daemon", "INFO")

# ==================== MAIN ====================
if __name__ == "__main__":
    daemon = UserSyncDaemon()
    
    while True:
        print("\n" + "="*70)
        print("🚀 DAEMON ĐỒNG BỘ 3 CHIỀU - PHIÊN BẢN SIÊU TỐI ƯU")
        print("="*70)
        print("1. Đồng bộ TOÀN BỘ một lần")
        print("2. Daemon TỰ ĐỘNG (thông minh - tự phân loại user)")
        print("3. Daemon ACTIVE (chỉ user hoạt động)")
        print("4. Daemon FULL (tất cả user)")
        print("5. Daemon với thời gian tùy chỉnh")
        print("6. Đẩy TẤT CẢ user lên Render")
        print("7. Kéo TẤT CẢ user từ Render về")
        print("8. Đồng bộ một user cụ thể")
        print("9. Thử lại push thất bại")
        print("10. Xem thống kê")
        print("11. Cấu hình tham số")
        print("12. Thoát")
        print("="*70)
        
        choice = input("Chọn chức năng (1-12): ").strip()
        
        if choice == "1":
            daemon.full_sync()
        
        elif choice == "2":
            daemon.run_daemon_optimized(interval=60, mode="auto")
        
        elif choice == "3":
            daemon.run_daemon_optimized(interval=30, mode="active")
        
        elif choice == "4":
            daemon.run_daemon_optimized(interval=120, mode="full")
        
        elif choice == "5":
            try:
                interval = int(input("Nhập thời gian (giây): "))
                mode = input("Chọn mode (auto/active/full): ").strip() or "auto"
                daemon.run_daemon_optimized(interval, mode)
            except ValueError:
                print("❌ Vui lòng nhập số!")
        
        elif choice == "6":
            daemon.sync_all_users_push()
        
        elif choice == "7":
            daemon.sync_all_users_pull()
        
        elif choice == "8":
            try:
                user_id = int(input("Nhập user_id: "))
                daemon.sync_user(user_id)
            except ValueError:
                print("❌ Vui lòng nhập số!")
        
        elif choice == "9":
            daemon.retry_failed_pushes()
        
        elif choice == "10":
            daemon.print_stats()
        
        elif choice == "11":
            print("\n⚙️ CẤU HÌNH HIỆN TẠI:")
            print(f"   • Batch size: {daemon.batch_size}")
            print(f"   • Workers: {daemon.max_workers}")
            print(f"   • Push timeout: {daemon.push_timeout}s")
            print(f"   • Pull timeout: {daemon.pull_timeout}s")
            print(f"   • Retry limit: {daemon.retry_limit}")
            
            new_batch = input("\nBatch size mới (Enter để giữ): ").strip()
            if new_batch:
                daemon.batch_size = int(new_batch)
            
            new_workers = input("Số workers mới (Enter để giữ): ").strip()
            if new_workers:
                daemon.max_workers = int(new_workers)
            
            print("✅ Đã cập nhật cấu hình!")
        
        elif choice == "12":
            print("\n👋 Tạm biệt!")
            break
        
        else:
            print("❌ Lựa chọn không hợp lệ!")
        
        if choice not in ["2", "3", "4", "5"]:
            input("\nNhấn Enter để tiếp tục...")