# sync_manager.py
import json
import os
import requests
import time
from datetime import datetime, timedelta
from database.models import db, User, DepositTransaction
import logging
# Đầu file, thêm imports
from datetime import datetime, timedelta, timezone

# Thêm sau imports
VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

logger = logging.getLogger(__name__)

class SyncManager:
    """Quản lý đồng bộ dữ liệu giữa local và Render - CHO DAEMON"""
    
    def __init__(self, app):
        self.app = app
        self.render_url = os.getenv('RENDER_URL', 'https://bot-thue-sms-v2.onrender.com')
        self.sync_file = "sync_state.json"
        self.last_sync = self._load_last_sync()
        self.pending_file = "pending_transactions.json"
        self.processed_transactions = set()
        
    def _load_last_sync(self):
        """Đọc thời gian đồng bộ cuối từ file"""
        try:
            if os.path.exists(self.sync_file):
                with open(self.sync_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return datetime.fromisoformat(data.get('last_sync', '2000-01-01T00:00:00'))
        except Exception as e:
            logger.error(f"❌ Lỗi đọc sync file: {e}")
        return datetime.now() - timedelta(days=30)
    
    def _save_last_sync(self, sync_time):
        """Lưu thời gian đồng bộ cuối"""
        try:
            with open(self.sync_file, 'w', encoding='utf-8') as f:
                json.dump({'last_sync': sync_time.isoformat()}, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Lỗi ghi sync file: {e}")
    
    def _save_pending_transactions(self, transactions):
        """Lưu các giao dịch pending để phòng khi mất điện"""
        try:
            data = []
            for t in transactions:
                data.append({
                    'id': t.transaction_id,
                    'user_id': t.user_id,
                    'amount': t.amount,
                    'created_at': t.created_at.isoformat(),
                    'retry_count': t.retry_count
                })
            
            with open(self.pending_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'transactions': data
                }, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Lỗi lưu pending: {e}")
    
    def _load_pending_transactions(self):
        """Khôi phục giao dịch pending khi bot khởi động"""
        try:
            if os.path.exists(self.pending_file):
                with open(self.pending_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('transactions', [])
        except Exception as e:
            logger.error(f"❌ Lỗi đọc pending: {e}")
        return []
    
    def test_connection(self):
        """Test kết nối đến Render"""
        try:
            response = requests.get(f"{self.render_url}/api/health", timeout=5)
            if response.status_code == 200:
                logger.info(f"✅ Kết nối Render thành công")
                return True
            else:
                logger.error(f"❌ Render trả về {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ Không thể kết nối Render: {e}")
            return False
    
    def sync_recent_transactions(self):
        """Đồng bộ giao dịch local - CHỈ XỬ LÝ GIAO DỊCH TRONG 10 PHÚT"""
        with self.app.app_context():
            time_threshold = datetime.now() - timedelta(minutes=10)
            
            pending = DepositTransaction.query.filter(
                DepositTransaction.status.in_(['pending', 'failed']),
                DepositTransaction.retry_count < 3,
                DepositTransaction.created_at > time_threshold
            ).order_by(DepositTransaction.created_at).all()
            
            total_pending = DepositTransaction.query.filter_by(
                status='pending'
            ).count()
            
            old_pending = total_pending - len(pending)
            
            logger.info(f"📊 Tổng pending: {total_pending} | Xử lý: {len(pending)} | Bỏ qua cũ: {old_pending}")
            
            success_count = 0
            fail_count = 0
            
            for trans in pending:
                if trans.transaction_id in self.processed_transactions:
                    logger.info(f"⏭️ Bỏ qua GD {trans.transaction_id} (đã xử lý)")
                    continue
                    
                try:
                    user = User.query.filter_by(user_id=trans.user_id).first()
                    if user:
                        old_balance = user.balance
                        user.balance += trans.amount
                        trans.status = 'completed'
                        trans.processed_at = datetime.now()
                        trans.synced_at = datetime.now()
                        
                        db.session.commit()
                        
                        self.processed_transactions.add(trans.transaction_id)
                        
                        logger.info(f"✅ Xử lý GD {trans.transaction_id}: +{trans.amount}đ | {old_balance}đ → {user.balance}đ")
                        success_count += 1
                    else:
                        logger.error(f"❌ Không tìm thấy user {trans.user_id}")
                        trans.status = 'failed'
                        db.session.commit()
                        fail_count += 1
                        
                except Exception as e:
                    logger.error(f"❌ Lỗi xử lý GD {trans.transaction_id}: {e}")
                    trans.retry_count += 1
                    db.session.commit()
                    fail_count += 1
            
            if pending:
                logger.info(f"📊 Kết quả: {success_count} thành công, {fail_count} thất bại")
            
            old_transactions = DepositTransaction.query.filter(
                DepositTransaction.status == 'pending',
                DepositTransaction.created_at <= time_threshold
            ).all()
            
            for trans in old_transactions:
                trans.status = 'expired'
                logger.info(f"⏰ Đánh dấu hết hạn GD cũ: {trans.transaction_id}")
            
            if old_transactions:
                db.session.commit()
                logger.info(f"⏰ Đã đánh dấu {len(old_transactions)} giao dịch cũ hết hạn")
            
            if len(self.processed_transactions) > 100:
                self.processed_transactions.clear()
    
    def sync_users_with_render(self):
        """Đồng bộ users với Render"""
        with self.app.app_context():
            users = User.query.all()
            logger.info(f"🔄 Đang đồng bộ {len(users)} users với Render...")
            
            success_count = 0
            fail_count = 0
            
            for user in users:
                try:
                    response = requests.post(
                        f"{self.render_url}/api/get-user-balance",
                        json={'user_id': user.user_id},
                        timeout=5
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        render_balance = data.get('balance')
                        
                        if render_balance is not None:
                            if render_balance > user.balance:
                                old_balance = user.balance
                                user.balance = render_balance
                                user.last_sync = datetime.now()
                                db.session.commit()
                                logger.info(f"✅ Cập nhật user {user.user_id}: {old_balance}đ → {render_balance}đ")
                                success_count += 1
                            elif render_balance < user.balance:
                                push_response = requests.post(
                                    f"{self.render_url}/api/update-balance",
                                    json={
                                        'user_id': user.user_id,
                                        'balance': user.balance,
                                        'username': user.username or f"user_{user.user_id}"
                                    },
                                    timeout=5
                                )
                                if push_response.status_code == 200:
                                    logger.info(f"📤 Push user {user.user_id}: {user.balance}đ lên Render")
                                    success_count += 1
                                else:
                                    logger.warning(f"⚠️ Push user {user.user_id} thất bại")
                                    fail_count += 1
                            else:
                                logger.info(f"✅ Số dư user {user.user_id} đã đồng bộ: {user.balance}đ")
                                success_count += 1
                        else:
                            logger.warning(f"⚠️ Render trả về balance null cho user {user.user_id}")
                            fail_count += 1
                    else:
                        logger.warning(f"⚠️ Render API error {response.status_code} cho user {user.user_id}")
                        fail_count += 1
                        
                except Exception as e:
                    logger.error(f"❌ Lỗi đồng bộ user {user.user_id}: {e}")
                    fail_count += 1
                
                time.sleep(0.1)
            
            logger.info(f"📊 Đồng bộ users: {success_count} thành công, {fail_count} thất bại")
            self._save_last_sync(datetime.now())
    
    def check_transactions_with_render(self):
        """Kiểm tra giao dịch pending với Render"""
        with self.app.app_context():
            pending = DepositTransaction.query.filter_by(
                status='pending'
            ).order_by(DepositTransaction.created_at.desc()).limit(20).all()
            
            logger.info(f"🔍 Kiểm tra {len(pending)} giao dịch pending với Render...")
            
            for trans in pending:
                if trans.transaction_id in self.processed_transactions:
                    continue
                    
                try:
                    response = requests.post(
                        f"{self.render_url}/api/check-transaction",
                        json={'code': trans.transaction_id},
                        timeout=5
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('exists') and data.get('status') == 'success':
                            user = User.query.filter_by(user_id=trans.user_id).first()
                            if user:
                                old_balance = user.balance
                                user.balance += trans.amount
                                trans.status = 'completed'
                                trans.processed_at = datetime.now()
                                trans.synced_at = datetime.now()
                                self.processed_transactions.add(trans.transaction_id)
                                db.session.commit()
                                logger.info(f"✅ Xác nhận GD {trans.transaction_id} từ Render: +{trans.amount}đ")
                                
                except Exception as e:
                    logger.error(f"❌ Lỗi check GD {trans.transaction_id}: {e}")
                
                time.sleep(0.1)
    
    def full_sync(self):
        """Đồng bộ toàn bộ"""
        logger.info("🔄 Bắt đầu đồng bộ toàn bộ...")
        
        self.sync_recent_transactions()
        self.sync_users_with_render()
        self.check_transactions_with_render()
        
        logger.info("✅ Đồng bộ toàn bộ hoàn tất")