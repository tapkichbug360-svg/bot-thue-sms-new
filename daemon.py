import sqlite3
import requests
import time
import os
from datetime import datetime, timedelta
# Đầu file, thêm imports
from datetime import datetime, timedelta, timezone

# Thêm sau imports
VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

RENDER_URL = "https://bot-thue-sms-new.onrender.com"

class UserSyncDaemon:
    def __init__(self):
        self.running = True
        self.last_sync = {}
    def send_telegram_notification(self, user_id, new_balance, amount):
        """Gửi thông báo Telegram khi có biến động số dư"""
        try:
            import requests
            from datetime import datetime
            
            BOT_TOKEN = os.getenv('BOT_TOKEN', '8561464326:AAG6NPFNvvFV0vFWQP1t8qUMo3WrjW5Un90')
            current_time = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
            
            message = (
                f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                f"• **Số tiền:** {amount:,}đ\n"
                f"• **Số dư mới:** {new_balance:,}đ\n"
                f"• **Thời gian:** {current_time}"
            )
            
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': user_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                print(f"     📨 Đã gửi thông báo Telegram cho user {user_id}")
            else:
                print(f"     ⚠️ Lỗi gửi Telegram: {response.status_code}")
                
        except Exception as e:
            print(f"     ⚠️ Lỗi gửi Telegram: {e}")
    
    def get_all_local_users(self):
        """Lấy tất cả user từ database local"""
        try:
            db_path = os.path.join('database', 'bot.db')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT user_id, username, balance FROM users')
            users = cursor.fetchall()
            conn.close()
            
            return [{'user_id': row[0], 'username': row[1], 'balance': row[2]} for row in users]
        except Exception as e:
            print(f"❌ Lỗi lấy user local: {e}")
            return []
    
    def get_all_local_transactions(self):
        """Lấy tất cả transaction pending từ local"""
        conn = None
        try:
            db_path = os.path.join('database', 'bot.db')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Dùng bảng deposit_transactions (khuyên dùng)
            cursor.execute("""
                SELECT transaction_id, amount, user_id
                FROM deposit_transactions 
                WHERE status = 'pending'
            """)
            
            pending = cursor.fetchall()
            
            result = []
            for trans_id, amount, user_id in pending:
                cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                user = cursor.fetchone()
                username = user[0] if user else f"user_{user_id}"
                
                result.append({
                    'code': trans_id,
                    'amount': amount,
                    'user_id': user_id,
                    'username': username
                })
            
            return result
        except sqlite3.OperationalError:
            # Bảng chưa tồn tại
            return []
        except Exception as e:
            print(f"❌ Lỗi lấy transaction local: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def push_user_to_render(self, user_id, username):
        """Đẩy user lên Render"""
        try:
            response = requests.post(
                f"{RENDER_URL}/api/check-user",
                json={'user_id': user_id, 'username': username},
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            print(f"  ❌ Lỗi push user {user_id}: {e}")
            return False
    
    def push_transaction_to_render(self, transaction):
        """Đẩy transaction lên Render - CÓ THÊM THỜI GIAN ĐỂ PHÂN BIỆT"""
        try:
            # Tạo payload với thời gian hiện tại
            payload = {
                'transactions': [{
                    'code': transaction['code'],
                    'amount': transaction['amount'],
                    'user_id': transaction['user_id'],
                    'username': transaction['username'],
                    'created_at': datetime.now().isoformat()  # THÊM THỜI GIAN
                }]
            }
            
            # Log để debug
            print(f"  📤 Push transaction {transaction['code']} lên Render (thời gian: {datetime.now().strftime('%H:%M:%S')})")
            
            response = requests.post(
                f"{RENDER_URL}/api/sync-pending",
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Push transaction {transaction['code']} thành công")
                print(f"     Synced: {result.get('synced', 0)}, Rejected: {result.get('rejected', 0)}")
                return True
            else:
                print(f"  ⚠️ Push transaction {transaction['code']} thất bại: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"     Chi tiết: {error_detail}")
                except:
                    pass
                return False
                
        except requests.exceptions.Timeout:
            print(f"  ⏰ Timeout push transaction {transaction['code']}")
            return False
        except Exception as e:
            print(f"  ❌ Lỗi push transaction {transaction['code']}: {e}")
            return False
    
    def push_user_balance_to_render(self, user_id, balance, username):
        """Push số dư local lên Render - CÓ KIỂM TRA ENDPOINT VÀ RETRY"""
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # Danh sách endpoint theo thứ tự ưu tiên
                endpoints = [
                    f"{RENDER_URL}/api/update-balance",        # Endpoint chính
                    f"{RENDER_URL}/api/update-user-balance",   # Endpoint phụ 1
                    f"{RENDER_URL}/api/sync-user-balance",     # Endpoint phụ 2
                    f"{RENDER_URL}/api/force-sync-user",       # Endpoint dự phòng
                    f"{RENDER_URL}/api/check-user"             # Endpoint cuối cùng
                ]
                
                # Log thử push
                print(f"  📤 Đang push user {user_id}: {balance}đ (lần thử {retry_count + 1})")
                
                for endpoint in endpoints:
                    try:
                        # Tạo payload phù hợp với từng endpoint
                        if "force-sync-user" in endpoint:
                            payload = {
                                'user_id': user_id,
                                'balance': balance,
                                'username': username
                            }
                        elif "check-user" in endpoint:
                            payload = {
                                'user_id': user_id,
                                'username': username
                            }
                            # Endpoint check-user không nhận balance
                            response = requests.post(endpoint, json=payload, timeout=5)
                            if response.status_code == 200:
                                print(f"  ✅ Đã xác nhận user {user_id} trên Render")
                                return True
                            continue
                        else:
                            payload = {
                                'user_id': user_id,
                                'balance': balance,
                                'username': username
                            }
                        
                        # Gửi request
                        response = requests.post(endpoint, json=payload, timeout=5)
                        
                        if response.status_code == 200:
                            print(f"  ✅ Đã push {balance}đ lên Render qua {endpoint.split('/')[-1]}")
                            
                            # Log chi tiết thành công
                            print(f"     User: {user_id}")
                            print(f"     Balance: {balance}đ")
                            print(f"     Time: {datetime.now().strftime('%H:%M:%S')}")
                            return True
                        else:
                            print(f"  ⏭️ {endpoint.split('/')[-1]} trả về {response.status_code}")
                            
                    except requests.exceptions.Timeout:
                        print(f"  ⏰ Timeout {endpoint.split('/')[-1]}")
                        continue
                    except requests.exceptions.ConnectionError:
                        print(f"  🔌 Lỗi kết nối {endpoint.split('/')[-1]}")
                        continue
                    except Exception as e:
                        print(f"  ⚠️ Lỗi {endpoint.split('/')[-1]}: {e}")
                        continue
                
                # Nếu đã thử hết endpoints mà vẫn thất bại
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = 2 ** retry_count  # 2s, 4s
                    print(f"  ⏳ Chờ {wait_time}s trước khi thử lại...")
                    time.sleep(wait_time)
                else:
                    print(f"  ❌ Push user {user_id} thất bại sau {max_retries + 1} lần thử")
                    
                    # Lưu lại để xử lý sau
                    self._save_failed_push(user_id, balance, username)
                    return False
                    
            except Exception as e:
                print(f"  ❌ Lỗi push balance: {e}")
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(2 ** retry_count)
                else:
                    return False
        
        return False

    def _save_failed_push(self, user_id, balance, username):
        """Lưu các push thất bại để xử lý sau"""
        try:
            failed_file = "failed_pushes.json"
            import json
            
            # Đọc file cũ
            if os.path.exists(failed_file):
                with open(failed_file, 'r') as f:
                    failed = json.load(f)
            else:
                failed = []
            
            # Thêm push mới
            failed.append({
                'user_id': user_id,
                'balance': balance,
                'username': username,
                'time': datetime.now().isoformat()
            })
            
            # Giới hạn 100 entry
            if len(failed) > 100:
                failed = failed[-100:]
            
            # Ghi lại
            with open(failed_file, 'w') as f:
                json.dump(failed, f, indent=2)
                
            print(f"  💾 Đã lưu push thất bại của user {user_id} để xử lý sau")
        except Exception as e:
            print(f"  ❌ Lỗi lưu failed push: {e}")
    
    def pull_user_from_render(self, user_id):
        """Kéo user từ Render về - GIỮ NGUYÊN LOGIC, THÊM FORCE UPDATE BALANCE VÀ GỬI TELEGRAM"""
        try:
            # Gọi API lấy thông tin user từ Render (có thời gian)
            response = requests.post(
                f"{RENDER_URL}/api/force-sync-user",
                json={'user_id': user_id},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                render_balance = data.get('balance')
                render_updated_at = data.get('updated_at')  # Thời gian từ Render
                
                if render_balance is None:
                    print(f"  ⚠️ User {user_id}: Render trả về thiếu balance")
                    return False
                
                db_path = os.path.join('database', 'bot.db')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Lấy số dư local và thời gian cập nhật
                cursor.execute('SELECT balance, updated_at FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                
                if result:
                    local_balance, local_updated_at = result
                else:
                    local_balance, local_updated_at = 0, None
                
                # Lấy username
                cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                user_data = cursor.fetchone()
                username = user_data[0] if user_data else f"user_{user_id}"
                
                # ===== SO SÁNH THỜI GIAN =====
                # Chuyển đổi thời gian về datetime object
                now = datetime.now()
                
                if local_updated_at:
                    local_time = datetime.fromisoformat(local_updated_at) if isinstance(local_updated_at, str) else local_updated_at
                else:
                    local_time = now  # Nếu chưa có, coi như mới nhất
                
                if render_updated_at:
                    render_time = datetime.fromisoformat(render_updated_at)
                else:
                    render_time = now  # Nếu Render không có, coi như cũ
                
                # ===== QUY TẮC: LẤY SỐ DƯ CỦA BÊN CÓ THỜI GIAN MUỘN HƠN =====
                if render_time > local_time:
                    # Render mới hơn → Cập nhật local
                    cursor.execute('''
                        UPDATE users 
                        SET balance = ?, updated_at = ? 
                        WHERE user_id = ?
                    ''', (render_balance, render_updated_at, user_id))
                    print(f"  💾 User {user_id}: Cập nhật từ Render (mới hơn)")
                    print(f"     Local: {local_balance}đ ({local_time.strftime('%H:%M:%S')})")
                    print(f"     Render: {render_balance}đ ({render_time.strftime('%H:%M:%S')}) → ĐÃ CẬP NHẬT")
                    
                    # Gửi thông báo nếu số dư thay đổi
                    if local_balance != render_balance:
                        self.send_telegram_notification(user_id, render_balance, render_balance - local_balance)
                        
                    conn.commit()
                    
                elif render_time < local_time:
                    # Local mới hơn → Push lên Render
                    print(f"  ⏫ User {user_id}: Push lên Render (local mới hơn)")
                    print(f"     Local: {local_balance}đ ({local_time.strftime('%H:%M:%S')}) → ĐẨY LÊN")
                    print(f"     Render: {render_balance}đ ({render_time.strftime('%H:%M:%S')})")
                    
                    # Cập nhật thời gian local trước khi push
                    cursor.execute('''
                        UPDATE users 
                        SET updated_at = ? 
                        WHERE user_id = ?
                    ''', (now.isoformat(), user_id))
                    conn.commit()
                    
                    # Push lên Render
                    self.push_user_balance_to_render(user_id, local_balance, username)
                else:
                    # Cùng thời gian → Giữ nguyên, chỉ cập nhật nếu khác số
                    if local_balance != render_balance:
                        print(f"  ⚠️ User {user_id}: Số dư lệch nhưng cùng thời gian")
                        
                        # === CHỈ CẬP NHẬT NẾU RENDER CAO HƠN LOCAL ===
                        if render_balance > local_balance:
                            cursor.execute('''
                                UPDATE users 
                                SET balance = ? 
                                WHERE user_id = ?
                            ''', (render_balance, user_id))
                            
                            # Gửi thông báo
                            amount_diff = render_balance - local_balance
                            self.send_telegram_notification(user_id, render_balance, amount_diff)
                            
                            conn.commit()
                            print(f"     ✅ Đã cập nhật balance: {local_balance}đ → {render_balance}đ (+{amount_diff}đ)")
                            
                        elif render_balance < local_balance:
                            print(f"     ⚠️ Render thấp hơn local: {render_balance}đ < {local_balance}đ")
                            print(f"        Giữ nguyên local (không cập nhật)")
                            
                        else:
                            # Trường hợp bằng nhau (không xảy ra vì đã check !=)
                            pass
                    else:
                        print(f"  ✅ User {user_id}: Đã đồng bộ {local_balance}đ")

                conn.close()
                return True
            return False
        except Exception as e:
            print(f"  ❌ Lỗi pull user {user_id}: {e}")
            return False
    
    def sync_all_users(self):
        """Đồng bộ tất cả user (2 chiều)"""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 ĐỒNG BỘ USER 2 CHIỀU...")
        
        local_users = self.get_all_local_users()
        print(f"📋 Local có {len(local_users)} user")
        
        # PUSH: Đẩy user local lên Render
        for user in local_users:
            if self.push_user_to_render(user['user_id'], user['username']):
                print(f"  ✅ Push user {user['user_id']}")
            time.sleep(0.2)
        
        # PULL: Kéo user từ Render về
        for user in local_users:
            self.pull_user_from_render(user['user_id'])
            time.sleep(0.2)
    
    def sync_transactions(self):
        """Đồng bộ tất cả transaction"""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 ĐỒNG BỘ TRANSACTION...")
        
        local_trans = self.get_all_local_transactions()
        print(f"📋 Local có {len(local_trans)} transaction pending")
        
        for trans in local_trans:
            if self.push_transaction_to_render(trans):
                print(f"  ✅ Push transaction {trans['code']}")
            time.sleep(0.2)
    
    def sync_user_balance(self, user_id):
        """Đồng bộ số dư user cụ thể từ Render về"""
        return self.pull_user_from_render(user_id)
    
    def run_daemon(self):
        """Chạy daemon tự động - ĐỒNG BỘ TẤT CẢ USER"""
        print("="*70)
        print("🚀 DAEMON ĐỒNG BỘ 2 CHIỀU - 10 GIÂY/LẦN")
        print("="*70)
        
        counter = 0
        while self.running:
            try:
                counter += 1
                print(f"\n🔄 Lần {counter} - {datetime.now().strftime('%H:%M:%S')}")
                
                # === LẤY DANH SÁCH USER LOCAL ===
                local_users = self.get_all_local_users()
                print(f"📋 Local có {len(local_users)} user")
                
                # === PUSH TẤT CẢ USER LÊN RENDER ===
                for user in local_users:
                    if self.push_user_to_render(user['user_id'], user['username']):
                        print(f"  ✅ Push user {user['user_id']}")
                    time.sleep(0.2)
                
                # === PULL TẤT CẢ USER TỪ RENDER VỀ ===
                for user in local_users:
                    self.pull_user_from_render(user['user_id'])
                    time.sleep(0.2)
                
                # === ĐỒNG BỘ TRANSACTION ===
                local_trans = self.get_all_local_transactions()
                print(f"📋 Có {len(local_trans)} transaction pending")
                for trans in local_trans:
                    if self.push_transaction_to_render(trans):
                        print(f"  ✅ Push transaction {trans['code']}")
                    time.sleep(0.2)
                
                time.sleep(10)  # 10 giây
                
            except KeyboardInterrupt:
                print("\n👋 Đã dừng daemon")
                self.running = False
                break
            except Exception as e:
                print(f"❌ Lỗi daemon: {e}")
                time.sleep(5)
    
    def stop(self):
        self.running = False

if __name__ == "__main__":
    daemon = UserSyncDaemon()
    
    print("="*70)
    print("🔄 CÔNG CỤ ĐỒNG BỘ 2 CHIỀU")
    print("="*70)
    print("1. Đồng bộ user một lần")
    print("2. Đồng bộ transaction một lần")
    print("3. Đồng bộ cả user + transaction")
    print("4. Chạy daemon (tự động 10 giây)")
    print("5. Đồng bộ user cụ thể")
    print("6. Thoát")
    print("="*70)
    
    choice = input("Chọn (1-6): ").strip()
    
    if choice == "1":
        daemon.sync_all_users()
    elif choice == "2":
        daemon.sync_transactions()
    elif choice == "3":
        daemon.sync_all_users()
        daemon.sync_transactions()
    elif choice == "4":
        daemon.run_daemon()
    elif choice == "5":
        uid = int(input("Nhập user_id: "))
        daemon.sync_user_balance(uid)
    else:
        print("👋 Tạm biệt!")