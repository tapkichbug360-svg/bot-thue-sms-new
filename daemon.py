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
        self.pull_timeout = 5           # Timeout pull (giây)
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
    def get_render_balance(self, user_id):
        """Lấy balance hiện tại từ Render - tránh push trùng"""
        try:
            response = requests.post(
                f"{RENDER_URL}/api/check-user",
                json={'user_id': user_id},
                timeout=3
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('balance')
        except Exception as e:
            self.log(f"⚠️ Lỗi lấy balance từ Render: {e}", "WARNING")
        return None
    
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
        
        # Kiểm tra psutil có khả dụng không
        try:
            self.log(f"• Memory: {psutil.Process().memory_percent():.1f}%", "PERF")
            self.log(f"• CPU: {psutil.Process().cpu_percent():.1f}%", "PERF")
        except:
            pass
        
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
            inactive_users = [u for u in all_users if u['user_id'] not in active_ids]
            
            self.log(f"⚡ Active users ({minutes}ph): {len(active_users)}/{len(all_users)}", "INFO")
            return active_users, inactive_users
            
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
        """Đẩy user lên Render - KHÔNG PUSH KHI BALANCE = 0"""
        
        # ===== QUAN TRỌNG: KHÔNG PUSH NẾU BALANCE = 0 =====
        if balance == 0:
            self.log(f"⏭️ User {user_id}: Balance = 0, bỏ qua push để tránh reset", "INFO")
            self.update_stats('push_success')  # Vẫn tính là thành công
            return True
        
        # KIỂM TRA BALANCE HIỆN TẠI TRÊN RENDER
        render_balance = self.get_render_balance(user_id)
        if render_balance is not None and render_balance == balance:
            self.log(f"⏭️ User {user_id}: Balance đã đồng bộ ({balance}đ), bỏ qua push", "INFO")
            self.update_stats('push_success')
            return True
        
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
                
                if response.status_code == 200:
                    self.update_stats('push_success')
                    self.log(f"✅ Push user {user_id}: {balance}đ thành công", "SUCCESS")
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
        """Đẩy nhiều user song song - LỌC USER CÓ BALANCE > 0"""
        if not users:
            return 0
        
        # CHỈ PUSH USER CÓ BALANCE > 0
        valid_users = [u for u in users if u['balance'] > 0]
        skipped = len(users) - len(valid_users)
        
        if skipped > 0:
            self.log(f"⏭️ Bỏ qua {skipped} user có balance = 0", "INFO")
        
        if not valid_users:
            return 0
            
        success = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for user in valid_users:
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
    def fix_reset_user(self, user_id, correct_balance, correct_username):
        """Fix user bị reset - Đặt lại balance đúng"""
        self.log(f"🔄 Fix user {user_id}: Đặt lại balance = {correct_balance}đ", "INFO")
        
        # Push balance đúng lên Render
        response = requests.post(
            f"{RENDER_URL}/api/sync-bidirectional",
            json={
                'user_id': user_id,
                'balance': correct_balance,
                'username': correct_username
            },
            timeout=5
        )
        
        if response.status_code == 200:
            self.log(f"✅ Fix user {user_id} thành công", "SUCCESS")
            return True
        else:
            self.log(f"❌ Fix user {user_id} thất bại", "ERROR")
            return False
    
    # ==================== KÉO DỮ LIỆU TỪ RENDER VỀ ====================
    def pull_user_from_render(self, user_id):
        """
        KÉO USER TỪ RENDER VỀ - CHỈ DÙNG sync-bidirectional, KHÔNG TẠO USER MỚI
        """
        try:
            self.log(f"📥 Đang kéo user {user_id} từ Render về...", "INFO")
            
            # Lấy balance hiện tại từ local
            local_balance = self.get_user_balance(user_id)
            
            # NẾU LOCAL = 0, BỎ QUA (TRÁNH TẠO USER MỚI TRÊN RENDER)
            if local_balance == 0:
                self.log(f"⏭️ User {user_id}: Local balance = 0, bỏ qua pull", "INFO")
                return True
            
            # DÙNG sync-bidirectional ĐỂ ĐỒNG BỘ
            response = requests.post(
                f"{RENDER_URL}/api/sync-bidirectional",
                json={
                    'user_id': user_id,
                    'balance': local_balance,
                    'username': f"user_{user_id}"
                },
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Nếu API trả về direct_update và có new_balance
                if data.get('direct_update') and data.get('new_balance'):
                    render_balance = data.get('new_balance')
                    
                    if render_balance != local_balance:
                        self.update_local_balance(user_id, render_balance)
                        diff = render_balance - local_balance
                        self.log(f"✅ User {user_id}: {local_balance}đ → {render_balance}đ ({diff:+,}đ)", "SUCCESS")
                        
                        # Gửi thông báo
                        if diff > 0:
                            self.send_telegram_notification(user_id, render_balance, diff, "NAP")
                        else:
                            self.send_telegram_notification(user_id, render_balance, diff, "TIÊU")
                    else:
                        self.log(f"✅ User {user_id}: Đã đồng bộ {local_balance}đ", "SUCCESS")
                    return True
                else:
                    self.log(f"✅ User {user_id}: Giữ nguyên {local_balance}đ", "SUCCESS")
                    return True
            else:
                self.log(f"⚠️ sync-bidirectional lỗi {response.status_code}", "WARNING")
                return False
                
        except Exception as e:
            self.log(f"❌ Lỗi pull user {user_id}: {e}", "ERROR")
            return False
    
    def pull_user_batch(self, users):
        """Kéo nhiều user song song - CÓ CẬP NHẬT BALANCE"""
        if not users:
            return 0
            
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
    def force_sync_user(self, user_id):
        """Force đồng bộ một user cụ thể"""
        self.log(f"🔄 Force sync user {user_id}...", "INFO")
        
        # Push lên Render
        balance = self.get_user_balance(user_id)
        username = f"user_{user_id}"
        self.push_user_to_render(user_id, balance, username, "force_sync")
        
        # Pull từ Render về
        result = self.pull_user_from_render(user_id)
        
        if result:
            self.log(f"✅ Force sync user {user_id} thành công", "SUCCESS")
        else:
            self.log(f"❌ Force sync user {user_id} thất bại", "ERROR")
        
        return result
    
    
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
    
    # ==================== ĐỒNG BỘ TẤT CẢ ====================
    def sync_all_users_push(self):
        """Đẩy tất cả user lên Render"""
        self.log("\n📤 ĐẨY TẤT CẢ USER LÊN RENDER:", "INFO")
        users = self.get_all_local_users()
        success = self.push_user_batch(users)
        self.log(f"✅ Đã đẩy {success}/{len(users)} user", "SUCCESS")
        return success
    
    def sync_all_users_pull(self):
        """Kéo tất cả user từ Render về"""
        self.log("\n📥 KÉO TẤT CẢ USER TỪ RENDER VỀ:", "INFO")
        users = self.get_all_local_users()
        success = self.pull_user_batch(users)
        self.log(f"✅ Đã kéo {success}/{len(users)} user", "SUCCESS")
        return success
    
    def full_sync(self):
        """Đồng bộ toàn bộ một lần"""
        self.log("="*70, "INFO")
        self.log("🚀 ĐỒNG BỘ TOÀN BỘ MỘT LẦN", "INFO")
        self.log("="*70, "INFO")
        
        self.retry_failed_pushes()
        time.sleep(1)
        
        push = self.sync_all_users_push()
        time.sleep(1)
        
        pull = self.sync_all_users_pull()
        time.sleep(1)
        
        trans = self.sync_all_transactions()
        
        self.log("="*70, "INFO")
        self.log(f"✅ HOÀN TẤT: Push {push}, Pull {pull}, Transactions {trans}", "SUCCESS")
        self.log("="*70, "INFO")
    
    def sync_all_transactions(self):
        """Đồng bộ tất cả transaction"""
        self.log("\n💳 ĐỒNG BỘ TRANSACTIONS:", "INFO")
        transactions = self.get_pending_transactions(limit=100)
        success = 0
        for trans in transactions:
            if self.push_transaction_to_render(trans):
                success += 1
            time.sleep(0.1)
        self.log(f"✅ Đã đồng bộ {success}/{len(transactions)} transaction", "SUCCESS")
        return success
    
    # ==================== DAEMON CHẠY NHANH ====================
    def run_daemon_fast(self, interval=5):
        """
        Daemon chạy 5 giây 1 lần - ĐỒNG BỘ NHANH
        """
        cycle_count = 0
        
        self.log("="*70, "INFO")
        self.log(f"🚀 DAEMON ĐỒNG BỘ NHANH - {interval} GIÂY/LẦN", "INFO")
        self.log("="*70, "INFO")
        
        while self.running:
            try:
                cycle_count += 1
                start_cycle = time.time()
                
                self.log(f"\n{'='*70}", "INFO")
                self.log(f"🔄 CYCLE #{cycle_count} - {datetime.now().strftime('%H:%M:%S')}", "INFO")
                
                # === LẤY USER MỚI NHẤT ===
                local_users = self.get_all_local_users()
                
                # === PUSH TẤT CẢ LÊN RENDER ===
                self.log(f"\n📤 PUSH {len(local_users)} USER:", "INFO")
                push_ok = self.push_user_batch(local_users)
                self.log(f"   ✅ Push: {push_ok}/{len(local_users)}", "SUCCESS")
                
                # === PULL TẤT CẢ TỪ RENDER VỀ ===
                self.log(f"\n📥 PULL {len(local_users)} USER:", "INFO")
                pull_ok = self.pull_user_batch(local_users)
                self.log(f"   ✅ Pull: {pull_ok}/{len(local_users)}", "SUCCESS")
                
                # === THỜI GIAN ===
                elapsed = time.time() - start_cycle
                wait_time = max(0.5, interval - elapsed)
                
                self.log(f"\n⏱️  Cycle time: {elapsed:.1f}s", "INFO")
                self.log(f"⏳ Chờ {wait_time:.1f}s...", "INFO")
                
                time.sleep(wait_time)
                
            except KeyboardInterrupt:
                self.log("\n👋 Đã dừng daemon", "INFO")
                self.running = False
                break
            except Exception as e:
                self.log(f"❌ Lỗi: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                time.sleep(5)
    
    # ==================== DAEMON TỐI ƯU ====================
    def run_daemon_optimized(self, interval=60, mode="auto"):
        """
        Daemon tối ưu với phân loại user
        """
        cycle_count = 0
        last_stats_time = time.time()
        
        self.log("="*70, "INFO")
        self.log(f"🚀 DAEMON TỐI ƯU - {interval} GIÂY/LẦN", "INFO")
        self.log(f"   • Mode: {mode}", "INFO")
        self.log("="*70, "INFO")
        
        while self.running:
            try:
                cycle_count += 1
                start_cycle = time.time()
                
                self.log(f"\n{'='*70}", "INFO")
                self.log(f"🔄 CYCLE #{cycle_count} - {datetime.now().strftime('%H:%M:%S')}", "INFO")
                
                # === LẤY USER THEO MODE ===
                if mode == "full":
                    active_users = self.get_all_local_users()
                    inactive_users = []
                else:
                    active_users, inactive_users = self.get_active_users(minutes=60)
                
                # === XỬ LÝ ACTIVE USERS ===
                if active_users:
                    self.log(f"\n⚡ XỬ LÝ {len(active_users)} USER ACTIVE:", "INFO")
                    
                    # Push active users
                    push_ok = self.push_user_batch(active_users)
                    self.log(f"   ✅ Push active: {push_ok}/{len(active_users)}", "SUCCESS")
                    
                    # Pull active users
                    pull_ok = self.pull_user_batch(active_users)
                    self.log(f"   ✅ Pull active: {pull_ok}/{len(active_users)}", "SUCCESS")
                
                # === XỬ LÝ INACTIVE USERS ===
                if inactive_users and mode != "active":
                    self.log(f"\n💤 XỬ LÝ {len(inactive_users)} USER INACTIVE:", "INFO")
                    
                    # Chỉ pull inactive users
                    pull_ok = self.pull_user_batch(inactive_users)
                    self.log(f"   ✅ Pull inactive: {pull_ok}/{len(inactive_users)}", "SUCCESS")
                
                # === THỐNG KÊ ===
                if time.time() - last_stats_time > self.stats_interval:
                    self.print_stats()
                    last_stats_time = time.time()
                
                # === THỜI GIAN ===
                elapsed = time.time() - start_cycle
                wait_time = max(1, interval - elapsed)
                
                self.log(f"\n⏱️  Cycle time: {elapsed:.1f}s", "INFO")
                self.log(f"⏳ Chờ {wait_time:.1f}s...", "INFO")
                
                time.sleep(wait_time)
                
            except KeyboardInterrupt:
                self.log("\n👋 Đã dừng daemon", "INFO")
                self.running = False
                break
            except Exception as e:
                self.log(f"❌ Lỗi: {e}", "ERROR")
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
        print("5. Daemon NHANH (5 giây/lần)")
        print("6. Daemon với thời gian tùy chỉnh")
        print("7. Đẩy TẤT CẢ user lên Render")
        print("8. Kéo TẤT CẢ user từ Render về")
        print("9. Đồng bộ một user cụ thể")
        print("10. Thử lại push thất bại")
        print("11. Xem thống kê")
        print("12. Cấu hình tham số")
        print("13. Thoát")
        print("="*70)
        
        choice = input("Chọn chức năng (1-13): ").strip()
        
        if choice == "1":
            daemon.full_sync()
        
        elif choice == "2":
            daemon.run_daemon_optimized(interval=60, mode="auto")
        
        elif choice == "3":
            daemon.run_daemon_optimized(interval=30, mode="active")
        
        elif choice == "4":
            daemon.run_daemon_optimized(interval=120, mode="full")
        
        elif choice == "5":
            daemon.run_daemon_fast(interval=5)
        
        elif choice == "6":
            try:
                interval = int(input("Nhập thời gian (giây): "))
                mode = input("Chọn mode (auto/active/full): ").strip() or "auto"
                daemon.run_daemon_optimized(interval, mode)
            except ValueError:
                print("❌ Vui lòng nhập số!")
        
        elif choice == "7":
            daemon.sync_all_users_push()
        
        elif choice == "8":
            daemon.sync_all_users_pull()
        
        elif choice == "9":
            try:
                user_id = int(input("Nhập user_id: "))
                daemon.sync_user(user_id)
            except ValueError:
                print("❌ Vui lòng nhập số!")
        
        elif choice == "10":
            daemon.retry_failed_pushes()
        
        elif choice == "11":
            daemon.print_stats()
        
        elif choice == "12":
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
        
        elif choice == "13":
            print("\n👋 Tạm biệt!")
            break
        
        else:
            print("❌ Lựa chọn không hợp lệ!")
        
        if choice not in ["2", "3", "4", "5", "6"]:
            input("\nNhấn Enter để tiếp tục...")