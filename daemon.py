import sqlite3
import requests
import time
import os
import json
from datetime import datetime, timedelta, timezone

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
            "RESET": "\033[0m"
        }
        color = colors.get(level, colors["INFO"])
        print(f"{color}[{timestamp}] {message}{colors['RESET']}")
    
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
    
    def get_pending_transactions(self):
        """Lấy các transaction đang chờ xử lý"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            # Thử với bảng deposit_transactions
            try:
                cursor.execute("""
                    SELECT transaction_id, amount, user_id, status
                    FROM deposit_transactions 
                    WHERE status = 'pending'
                """)
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
    
    # ==================== GỬI THÔNG BÁO TELEGRAM ====================
    def send_telegram_notification(self, user_id, new_balance, amount, type="NAP"):
        """Gửi thông báo Telegram - TIMEOUT 10s"""
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
            
            # TIMEOUT 10s
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                self.log(f"📨 Đã gửi thông báo Telegram cho user {user_id}", "SUCCESS")
            else:
                self.log(f"⚠️ Lỗi gửi Telegram: {response.status_code}", "WARNING")
                
        except requests.exceptions.Timeout:
            self.log(f"⏰ Telegram timeout (bỏ qua)", "WARNING")
        except Exception as e:
            self.log(f"⚠️ Lỗi gửi Telegram: {e}", "WARNING")
    
    # ==================== ĐẨY DỮ LIỆU LÊN RENDER ====================
    def push_user_to_render(self, user_id, balance, username, reason=""):
        """
        ĐẨY USER TỪ LOCAL LÊN RENDER - DÙNG sync-bidirectional
        """
        max_retries = 2
        retry_count = 0
        
        # Danh sách API ưu tiên - sync-bidirectional LÊN ĐẦU
        endpoints = [
            {
                "url": f"{RENDER_URL}/api/sync-bidirectional",  # ✅ API HOẠT ĐỘNG TỐT
                "payload": {
                    'user_id': user_id,
                    'balance': balance,
                    'username': username
                }
            },
            {
                "url": f"{RENDER_URL}/api/update-user",  # ⚠️ Dự phòng
                "payload": {
                    'user_id': user_id,
                    'balance': balance,
                    'username': username
                }
            },
            {
                "url": f"{RENDER_URL}/api/check-user",  # ⚠️ Dự phòng
                "payload": {
                    'user_id': user_id,
                    'username': username
                }
            }
        ]
        
        while retry_count < max_retries:
            for endpoint in endpoints:
                try:
                    self.log(f"📤 Push user {user_id} qua {endpoint['url'].split('/')[-1]} [Lần {retry_count + 1}]", "INFO")
                    
                    response = requests.post(
                        endpoint["url"], 
                        json=endpoint["payload"], 
                        timeout=5
                    )
                    
                    if response.status_code == 200:
                        self.log(f"✅ Push user {user_id} thành công!", "SUCCESS")
                        return True
                    else:
                        self.log(f"⏭️ {endpoint['url'].split('/')[-1]} trả về {response.status_code}", "WARNING")
                        
                except Exception as e:
                    self.log(f"⚠️ Lỗi: {e}", "WARNING")
                
                time.sleep(0.3)
            
            retry_count += 1
            if retry_count < max_retries:
                self.log(f"⏳ Chờ 2s trước khi thử lại...", "INFO")
                time.sleep(2)
        
        # Nếu thất bại
        self._save_failed_push(user_id, balance, username, reason)
        self.log(f"❌ Push user {user_id} thất bại", "ERROR")
        return False
    
    def _save_failed_push(self, user_id, balance, username, reason):
        """Lưu các push thất bại để xử lý sau"""
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
            
            # Giới hạn 100 entry
            if len(failed) > 100:
                failed = failed[-100:]
            
            with open(self.failed_pushes_file, 'w') as f:
                json.dump(failed, f, indent=2)
            
            self.log(f"💾 Đã lưu push thất bại của user {user_id}", "WARNING")
        except Exception as e:
            self.log(f"❌ Lỗi lưu failed push: {e}", "ERROR")
    
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
            
            self.log(f"📤 Push transaction {transaction['code']} lên Render", "INFO")
            
            response = requests.post(
                f"{RENDER_URL}/api/sync-pending",
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                self.log(f"✅ Push transaction {transaction['code']} thành công", "SUCCESS")
                self.log(f"   Synced: {result.get('synced', 0)}, Rejected: {result.get('rejected', 0)}", "INFO")
                
                # Cập nhật status trong local
                self._update_transaction_status(transaction['code'], 'synced')
                return True
            else:
                self.log(f"⚠️ Push transaction {transaction['code']} thất bại: {response.status_code}", "WARNING")
                return False
                
        except Exception as e:
            self.log(f"❌ Lỗi push transaction {transaction['code']}: {e}", "ERROR")
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
            self.log(f"❌ Lỗi cập nhật transaction {transaction_code}: {e}", "ERROR")
    
    def retry_failed_pushes(self):
        """Thử lại các push thất bại"""
        try:
            if not os.path.exists(self.failed_pushes_file):
                return
            
            with open(self.failed_pushes_file, 'r') as f:
                failed = json.load(f)
            
            if not failed:
                return
            
            self.log(f"🔄 Đang thử lại {len(failed)} push thất bại...", "INFO")
            
            success = []
            remaining = []
            
            for item in failed:
                if self.push_user_to_render(
                    item['user_id'], 
                    item['balance'], 
                    item['username'], 
                    item.get('reason', 'retry')
                ):
                    success.append(item)
                else:
                    remaining.append(item)
                time.sleep(0.5)
            
            # Lưu lại những cái vẫn thất bại
            with open(self.failed_pushes_file, 'w') as f:
                json.dump(remaining, f, indent=2)
            
            self.log(f"✅ Thử lại thành công: {len(success)}", "SUCCESS")
            self.log(f"⏳ Còn lại: {len(remaining)}", "INFO")
            
        except Exception as e:
            self.log(f"❌ Lỗi retry failed pushes: {e}", "ERROR")
    
    # ==================== KÉO DỮ LIỆU TỪ RENDER VỀ ====================
    def pull_user_from_render(self, user_id):
        """
        KÉO USER TỪ RENDER VỀ - DÙNG sync-bidirectional
        """
        try:
            self.log(f"📥 Đang kéo user {user_id} từ Render về...", "INFO")
            
            # THỬ sync-bidirectional TRƯỚC
            response = requests.post(
                f"{RENDER_URL}/api/sync-bidirectional",
                json={
                    'user_id': user_id,
                    'balance': self.get_user_balance(user_id),
                    'username': f"user_{user_id}"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                render_balance = data.get('balance')
                
                if render_balance is not None:
                    local_balance = self.get_user_balance(user_id)
                    
                    if render_balance != local_balance:
                        self.update_local_balance(user_id, render_balance)
                        diff = render_balance - local_balance
                        self.log(f"✅ User {user_id}: {local_balance}đ → {render_balance}đ ({diff:+,}đ)", "SUCCESS")
                        
                        # Gửi thông báo
                        try:
                            if diff > 0:
                                self.send_telegram_notification(user_id, render_balance, diff, "NAP")
                            else:
                                self.send_telegram_notification(user_id, render_balance, diff, "TIÊU")
                        except:
                            pass
                    else:
                        self.log(f"✅ User {user_id}: Đã đồng bộ {local_balance}đ", "SUCCESS")
                    return True
            
            # Thử force-sync-user nếu sync-bidirectional không hoạt động
            self.log(f"⚠️ sync-bidirectional trả về {response.status_code}, thử force-sync-user", "WARNING")
            
            response2 = requests.post(
                f"{RENDER_URL}/api/force-sync-user",
                json={'user_id': user_id},
                timeout=10
            )
            
            if response2.status_code == 200:
                data2 = response2.json()
                render_balance = data2.get('balance')
                
                if render_balance is not None:
                    local_balance = self.get_user_balance(user_id)
                    
                    if render_balance != local_balance:
                        self.update_local_balance(user_id, render_balance)
                        diff = render_balance - local_balance
                        self.log(f"✅ User {user_id}: {local_balance}đ → {render_balance}đ ({diff:+,}đ) [force-sync]", "SUCCESS")
                    else:
                        self.log(f"✅ User {user_id}: Đã đồng bộ {local_balance}đ", "SUCCESS")
                    return True
            else:
                self.log(f"⚠️ force-sync-user lỗi {response2.status_code}", "WARNING")
                return False
                
        except requests.exceptions.Timeout:
            self.log(f"⏰ Timeout khi kéo user {user_id}", "WARNING")
            return False
        except Exception as e:
            self.log(f"❌ Lỗi pull user {user_id}: {e}", "ERROR")
            return False
    
    # ==================== ĐỒNG BỘ USER CỤ THỂ ====================
    def sync_user(self, user_id):
        """Đồng bộ một user cụ thể"""
        self.log(f"🔄 Đồng bộ user {user_id}...", "INFO")
        
        # Lấy thông tin user
        balance = self.get_user_balance(user_id)
        username = f"user_{user_id}"
        
        # Push lên Render
        push_success = self.push_user_to_render(user_id, balance, username, "sync_single")
        
        # Pull từ Render về
        pull_success = self.pull_user_from_render(user_id)
        
        if push_success and pull_success:
            self.log(f"✅ Đồng bộ user {user_id} thành công", "SUCCESS")
        else:
            self.log(f"⚠️ Đồng bộ user {user_id} chưa hoàn chỉnh", "WARNING")
        
        return push_success and pull_success
    
    # ==================== ĐỒNG BỘ TOÀN BỘ ====================
    def sync_all_users_push(self):
        """Đẩy TẤT CẢ user lên Render"""
        self.log("\n📤 ĐẨY TẤT CẢ USER LÊN RENDER:", "INFO")
        
        local_users = self.get_all_local_users()
        
        success_count = 0
        for user in local_users:
            if self.push_user_to_render(
                user['user_id'], 
                user['balance'], 
                user['username'], 
                "sync_all"
            ):
                success_count += 1
            time.sleep(0.2)
        
        self.log(f"✅ Đã đẩy {success_count}/{len(local_users)} user lên Render", "SUCCESS")
        return success_count
    
    def sync_all_users_pull(self):
        """Kéo TẤT CẢ user từ Render về"""
        self.log("\n📥 KÉO TẤT CẢ USER TỪ RENDER VỀ:", "INFO")
        
        local_users = self.get_all_local_users()
        
        success_count = 0
        for user in local_users:
            if self.pull_user_from_render(user['user_id']):
                success_count += 1
            time.sleep(0.2)
        
        self.log(f"✅ Đã kéo {success_count}/{len(local_users)} user từ Render về", "SUCCESS")
        return success_count
    
    def sync_all_transactions(self):
        """Đồng bộ tất cả transaction"""
        self.log("\n💳 ĐỒNG BỘ TRANSACTIONS:", "INFO")
        
        transactions = self.get_pending_transactions()
        self.log(f"📋 Có {len(transactions)} transaction pending", "INFO")
        
        success_count = 0
        for trans in transactions:
            if self.push_transaction_to_render(trans):
                success_count += 1
            time.sleep(0.2)
        
        self.log(f"✅ Đã đồng bộ {success_count}/{len(transactions)} transaction", "SUCCESS")
        return success_count
    
    def full_sync(self):
        """Đồng bộ TOÀN BỘ (Push + Pull + Transactions)"""
        self.log("="*70, "INFO")
        self.log("🚀 BẮT ĐẦU ĐỒNG BỘ TOÀN BỘ 3 CHIỀU", "INFO")
        self.log("="*70, "INFO")
        
        # 1. Thử lại các push thất bại
        self.retry_failed_pushes()
        time.sleep(1)
        
        # 2. Đẩy tất cả user lên Render
        push_count = self.sync_all_users_push()
        time.sleep(1)
        
        # 3. Kéo tất cả user từ Render về
        pull_count = self.sync_all_users_pull()
        time.sleep(1)
        
        # 4. Đồng bộ transactions
        trans_count = self.sync_all_transactions()
        
        self.log("="*70, "INFO")
        self.log(f"✅ HOÀN TẤT ĐỒNG BỘ TOÀN BỘ", "SUCCESS")
        self.log(f"   Push: {push_count} user", "INFO")
        self.log(f"   Pull: {pull_count} user", "INFO")
        self.log(f"   Transactions: {trans_count}", "INFO")
        self.log("="*70, "INFO")
    
    # ==================== DAEMON CHẠY NỀN ====================
    def run_daemon(self, interval=10):
        """Chạy daemon tự động"""
        cycle_count = 0
        
        self.log("="*70, "INFO")
        self.log(f"🚀 DAEMON ĐỒNG BỘ 3 CHIỀU - {interval} GIÂY/LẦN", "INFO")
        self.log("="*70, "INFO")
        
        while self.running:
            try:
                cycle_count += 1
                vn_time = get_vn_time()
                
                self.log(f"\n{'='*70}", "INFO")
                self.log(f"🔄 CYCLE #{cycle_count} - {vn_time.strftime('%H:%M:%S %d/%m/%Y')}", "INFO")
                
                # === THỬ LẠI PUSH THẤT BẠI ===
                self.retry_failed_pushes()
                
                # === LẤY DANH SÁCH USER ===
                local_users = self.get_all_local_users()
                
                # === PUSH USER LÊN RENDER ===
                self.log("\n📤 ĐẨY USER LÊN RENDER:", "INFO")
                push_success = 0
                for user in local_users:
                    if self.push_user_to_render(
                        user['user_id'], 
                        user['balance'], 
                        user['username']
                    ):
                        push_success += 1
                    time.sleep(0.2)
                
                # === PULL USER TỪ RENDER VỀ ===
                self.log("\n📥 KÉO USER TỪ RENDER VỀ:", "INFO")
                pull_success = 0
                for user in local_users:
                    if self.pull_user_from_render(user['user_id']):
                        pull_success += 1
                    time.sleep(0.2)
                
                # === ĐỒNG BỘ TRANSACTIONS ===
                transactions = self.get_pending_transactions()
                if transactions:
                    trans_success = 0
                    for trans in transactions:
                        if self.push_transaction_to_render(trans):
                            trans_success += 1
                        time.sleep(0.2)
                    self.log(f"\n✅ Đã đồng bộ {trans_success}/{len(transactions)} transaction", "SUCCESS")
                
                # === THỐNG KÊ ===
                self.log(f"\n📊 THỐNG KÊ CYCLE #{cycle_count}:", "INFO")
                self.log(f"   • Push: {push_success}/{len(local_users)}", "INFO")
                self.log(f"   • Pull: {pull_success}/{len(local_users)}", "INFO")
                self.log(f"⏳ Chờ {interval}s...", "INFO")
                
                # CHỜ
                for i in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except KeyboardInterrupt:
                self.log("\n👋 Đã dừng daemon", "INFO")
                self.running = False
                break
            except Exception as e:
                self.log(f"❌ Lỗi daemon: {e}", "ERROR")
                time.sleep(5)
    
    def stop(self):
        """Dừng daemon"""
        self.running = False
        self.log("🛑 Đã dừng daemon", "INFO")

# ==================== MAIN ====================
if __name__ == "__main__":
    daemon = UserSyncDaemon()
    
    while True:
        print("\n" + "="*70)
        print("🔄 CÔNG CỤ ĐỒNG BỘ 3 CHIỀU - RENDER = LOCAL = DAEMON")
        print("="*70)
        print("1. Đồng bộ TOÀN BỘ một lần (Push + Pull + Transactions)")
        print("2. Chạy DAEMON tự động (mặc định 10 giây)")
        print("3. Chạy DAEMON với thời gian tùy chỉnh")
        print("4. Đẩy TẤT CẢ user lên Render")
        print("5. Kéo TẤT CẢ user từ Render về")
        print("6. Đồng bộ một user cụ thể")
        print("7. Đồng bộ transactions")
        print("8. Thử lại các push thất bại")
        print("9. Xem danh sách push thất bại")
        print("10. Thoát")
        print("="*70)
        
        choice = input("Chọn chức năng (1-10): ").strip()
        
        if choice == "1":
            daemon.full_sync()
        
        elif choice == "2":
            daemon.run_daemon(10)
        
        elif choice == "3":
            try:
                interval = int(input("Nhập thời gian giữa các lần đồng bộ (giây): "))
                daemon.run_daemon(interval)
            except ValueError:
                print("❌ Vui lòng nhập số!")
        
        elif choice == "4":
            daemon.sync_all_users_push()
        
        elif choice == "5":
            daemon.sync_all_users_pull()
        
        elif choice == "6":
            try:
                user_id = int(input("Nhập user_id: "))
                daemon.sync_user(user_id)
            except ValueError:
                print("❌ Vui lòng nhập số!")
        
        elif choice == "7":
            daemon.sync_all_transactions()
        
        elif choice == "8":
            daemon.retry_failed_pushes()
        
        elif choice == "9":
            try:
                if os.path.exists(daemon.failed_pushes_file):
                    with open(daemon.failed_pushes_file, 'r') as f:
                        failed = json.load(f)
                    print(f"\n📋 Danh sách push thất bại ({len(failed)}):")
                    for item in failed:
                        print(f"   • User {item['user_id']}: {item['balance']}đ - {item.get('reason', 'N/A')}")
                else:
                    print("📭 Không có push thất bại nào!")
            except Exception as e:
                print(f"❌ Lỗi: {e}")
        
        elif choice == "10":
            print("\n👋 Tạm biệt!")
            break
        
        else:
            print("❌ Lựa chọn không hợp lệ!")
        
        if choice not in ["2", "3"]:
            input("\nNhấn Enter để tiếp tục...")