import logging
import os
import sys
import atexit
import asyncio
import time
import requests
import shutil
import threading
from database.models import SyncedTransaction
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from database.models import db, User, Rental, Transaction
from handlers.sepay import setup_sepay_webhook
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot
from sqlalchemy import or_
from dotenv import load_dotenv

# Telegram imports
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import Update

# Import từ handlers
from handlers.start import start_command, menu_command, cancel, help_command, check_command
from handlers.rent import (
    rent_command, rent_service_callback, rent_network_callback,
    rent_confirm_callback, rent_check_callback, rent_view_callback,
    rent_cancel_callback, rent_list_callback, rent_reuse_callback
)
from handlers.balance import balance_command
from handlers.deposit import deposit_command, deposit_amount_callback, deposit_check_callback
from handlers.callback import menu_callback

# ===== BACKUP DATABASE TỰ ĐỘNG =====
# Cấu hình backup
BACKUP_INTERVAL = 60  # Backup mỗi 60 giây
BACKUP_FOLDER = 'database/backups'
MAX_BACKUPS = 50  # Giữ tối đa 50 bản backup gần nhất

# Tạo thư mục backup nếu chưa có
if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)
    logger = logging.getLogger(__name__)
    logger.info(f"📁 Đã tạo thư mục backup: {BACKUP_FOLDER}")

def backup_database():
    """Backup database theo giây"""
    logger = logging.getLogger(__name__)
    try:
        src = 'database/bot.db'
        if not os.path.exists(src):
            logger.warning(f"⚠️ Không tìm thấy database: {src}")
            return
        
        # Tạo tên file backup với timestamp giây
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dst = f'{BACKUP_FOLDER}/bot_backup_{timestamp}.db'
        
        # Copy database
        shutil.copy2(src, dst)
        logger.info(f"✅ Backup thành công: {dst}")
        
        # Xóa các backup cũ
        cleanup_old_backups()
        
    except Exception as e:
        logger.error(f"❌ Lỗi backup: {e}")

def cleanup_old_backups():
    """Giữ lại MAX_BACKUPS bản gần nhất, xóa các bản cũ"""
    logger = logging.getLogger(__name__)
    try:
        backups = []
        for f in os.listdir(BACKUP_FOLDER):
            if f.startswith('bot_backup_') and f.endswith('.db'):
                path = os.path.join(BACKUP_FOLDER, f)
                backups.append((path, os.path.getmtime(path)))
        
        # Sắp xếp theo thời gian (cũ nhất trước)
        backups.sort(key=lambda x: x[1])
        
        # Xóa các bản cũ hơn MAX_BACKUPS
        while len(backups) > MAX_BACKUPS:
            oldest = backups.pop(0)
            os.remove(oldest[0])
            logger.info(f"🗑️ Đã xóa backup cũ: {os.path.basename(oldest[0])}")
            
    except Exception as e:
        logger.error(f"❌ Lỗi dọn backup: {e}")

def auto_backup_loop():
    """Vòng lặp backup tự động"""
    logger = logging.getLogger(__name__)
    while True:
        backup_database()
        time.sleep(BACKUP_INTERVAL)

# ===== ĐỌC BIẾN MÔI TRƯỜNG =====
import os
from dotenv import load_dotenv

# Load file .env nếu có (cho local)
load_dotenv()

# Đọc từ biến môi trường (Render)
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID')
MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
MB_BIN = os.getenv('MB_BIN', '970422')
SEPAY_TOKEN = os.getenv('SEPAY_TOKEN')
RENDER_URL = os.getenv('RENDER_URL')

# Kiểm tra biến bắt buộc
if not BOT_TOKEN:
    print("❌ KHÔNG TÌM THẤY BOT_TOKEN")
    print("📋 Các biến môi trường hiện có:")
    for key in os.environ.keys():
        print(f"   - {key}")
    sys.exit(1)

if not API_KEY:
    print("❌ KHÔNG TÌM THẤY API_KEY")
    sys.exit(1)
if not BASE_URL:
    print("❌ KHÔNG TÌM THẤY BASE_URL")
    sys.exit(1)

print("✅ Đã đọc tất cả biến môi trường thành công!")
print(f"✅ BOT_TOKEN: {BOT_TOKEN[:10]}...")
print(f"✅ API_KEY: {API_KEY[:10]}...")
print(f"✅ BASE_URL: {BASE_URL}")

# Múi giờ Việt Nam (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

# ===== CẤU HÌNH LOGGING =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== TẠO THƯ MỤC DATABASE =====
# Tạo thư mục database nếu chưa tồn tại
db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database')
os.makedirs(db_dir, exist_ok=True)
logger.info(f"📁 Thư mục database: {db_dir}")

# ===== KHỞI TẠO FLASK APP =====
app = Flask(__name__)

# Đường dẫn database
db_path = os.path.join(db_dir, 'bot.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
logger.info(f"🗄️ Database path: {db_path}")

# Khởi tạo database với Flask app
db.init_app(app)

# ===== TẠO DATABASE =====
with app.app_context():
    try:
        db.create_all()
        logger.info("✅ Database đã được tạo/sẵn sàng!")
        
        # Kiểm tra số lượng bảng
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        logger.info(f"📊 Các bảng trong database: {tables}")
        
        # Kiểm tra và tạo bảng synced_transactions nếu chưa có
        if 'synced_transactions' not in tables:
            SyncedTransaction.__table__.create(db.engine)
            logger.info("✅ Đã tạo bảng synced_transactions")
            
    except Exception as e:
        logger.error(f"❌ Lỗi tạo database: {e}")

# ===== THIẾT LẬP WEBHOOK SEPAY =====
setup_sepay_webhook(app)

# ===== ROUTE TRANG CHỦ =====
@app.route('/')
def home():
    return "Bot đang chạy! MBBank: 666666291005 - NGUYEN THE LAM"

# ===== BIẾN TOÀN CỤC =====
last_check_time = get_vn_time() - timedelta(minutes=1)
processed_transactions = set()
user_cache = {}

# ===== HÀM KIỂM TRA SỐ HẾT HẠN =====
def check_expired_rentals():
    """Kiểm tra và tự động hoàn tiền cho các số hết hạn + GỬI TELEGRAM"""
    with app.app_context():
        try:
            expired_rentals = Rental.query.filter(
                Rental.status == 'waiting',
                Rental.expires_at < get_vn_time()
            ).all()

            for rental in expired_rentals:
                user = get_or_create_user(rental.user_id)
                if user:
                    refund = rental.price_charged
                    old_balance = user.balance
                    
                    # ===== BƯỚC 1: CẬP NHẬT LOCAL NGAY =====
                    user.balance += refund
                    rental.status = 'expired'
                    rental.updated_at = get_vn_time()
                    db.session.commit()

                    logger.info(f"✅ LOCAL UPDATE: User {user.user_id}: {old_balance}đ → {user.balance}đ (+{refund}đ)")
                    
                    # ===== BƯỚC 2: PUSH LÊN RENDER (KHÔNG CHỜ) =====
                    try:
                        RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-new.onrender.com')
                        push_data = {
                            'user_id': user.user_id,
                            'balance': user.balance,
                            'username': user.username or f"user_{user.user_id}"
                        }
                        threading.Thread(target=lambda: requests.post(
                            f"{RENDER_URL}/api/sync-bidirectional",
                            json=push_data,
                            timeout=2
                        )).start()
                        logger.info(f"📤 Push lên Render: {user.balance}đ")
                    except Exception as e:
                        logger.error(f"❌ Lỗi push: {e}")
                    
                    # ===== BƯỚC 3: GỬI TELEGRAM THÔNG BÁO =====
                    if BOT_TOKEN:
                        try:
                            # Tạo bot và gửi message
                            bot = Bot(token=BOT_TOKEN)
                            message = (
                                f"⏰ **SỐ ĐÃ HẾT HẠN & HOÀN TIỀN**\n\n"
                                f"• **Số điện thoại:** `{rental.phone_number}`\n"
                                f"• **Dịch vụ:** {rental.service_name}\n"
                                f"• **Số tiền hoàn:** `{refund:,}đ`\n"
                                f"• **Số dư mới:** `{user.balance:,}đ`\n"
                                f"• **Thời gian:** `{get_vn_time().strftime('%H:%M:%S %d/%m/%Y')}`\n\n"
                                f"💡 *Số đã hết thời gian chờ OTP*"
                            )
                            
                            # Gửi message bất đồng bộ
                            asyncio.run(send_telegram_message(user.user_id, message))
                            logger.info(f"📨 Đã gửi Telegram thông báo hoàn tiền cho user {user.user_id}")
                        except Exception as e:
                            logger.error(f"❌ Lỗi gửi Telegram: {e}")
        except Exception as e:
            logger.error(f"Lỗi kiểm tra số hết hạn: {e}")


async def send_telegram_message(chat_id, message):
    """Gửi tin nhắn Telegram"""
    if not BOT_TOKEN:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=chat_id, 
            text=message, 
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Lỗi gửi Telegram: {e}")

# ===== HÀM GET_OR_CREATE_USER =====
def get_or_create_user(user_id, username=None):
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        user = User(
            user_id=user_id,
            username=username or f"user_{user_id}",
            balance=0,
            created_at=get_vn_time(),
            last_active=get_vn_time()
        )
        db.session.add(user)
        db.session.flush()
        logger.info(f"🆕 ĐÃ TẠO USER MỚI: {user_id} - {user.username}")
    return user

# ===== API 1: KIỂM TRA GIAO DỊCH =====
@app.route('/api/check-transaction', methods=['POST'])
def api_check_transaction():
    try:
        data = request.json
        code = data.get('code')
        
        with app.app_context():
            transaction = Transaction.query.filter_by(transaction_code=code).first()
            if transaction:
                user = User.query.get(transaction.user_id)
                return jsonify({
                    "success": True,
                    "exists": True,
                    "status": transaction.status,
                    "amount": transaction.amount,
                    "user_id": user.user_id if user else None,
                    "created_at": transaction.created_at.isoformat() if transaction.created_at else None
                }), 200
            return jsonify({
                "success": True,
                "exists": False,
                "message": "Transaction not found"
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 2: ĐỒNG BỘ PENDING TỪ LOCAL =====
@app.route('/api/sync-pending', methods=['POST'])
def api_sync_pending():
    try:
        data = request.json
        transactions = data.get('transactions', [])
        
        with app.app_context():
            synced = 0
            skipped = 0
            rejected = 0
            
            for t in transactions:
                code = t['code']
                amount = t['amount']
                user_id = t['user_id']
                username = t.get('username')
                trans_time_str = t.get('created_at')
                
                # === CHUYỂN THỜI GIAN TỪ STRING ===
                trans_time = None
                if trans_time_str:
                    try:
                        trans_time = datetime.fromisoformat(trans_time_str)
                    except:
                        trans_time = datetime.now()
                else:
                    trans_time = datetime.now()
                
                # === TÌM CÁC GIAO DỊCH CÙNG MÃ ===
                existing_trans = Transaction.query.filter_by(
                    transaction_code=code
                ).first()
                
                existing_sync = SyncedTransaction.query.filter_by(
                    transaction_code=code
                ).first()
                
                # === NẾU ĐÃ CÓ GIAO DỊCH TRONG DB ===
                if existing_trans:
                    # Lấy thời gian giao dịch cũ
                    old_time = existing_trans.created_at
                    time_diff = abs((trans_time - old_time).total_seconds())
                    
                    # Nếu thời gian KHÁC NHAU (trên 1 giây) -> Cho phép
                    if time_diff > 1:  # Khác thời gian
                        logger.info(f"✅ Mã {code} có thời gian khác ({time_diff:.0f}s), cho phép đồng bộ")
                        # VẪN CHO PHÉP TẠO GIAO DỊCH MỚI
                    else:
                        # CÙNG THỜI GIAN -> Từ chối
                        logger.warning(f"⏭️ Mã {code} đã tồn tại với cùng thời gian, từ chối")
                        rejected += 1
                        continue
                
                # === KIỂM TRA TRONG BẢNG SYNCED ===
                if existing_sync:
                    old_sync_time = existing_sync.synced_at
                    time_diff = abs((trans_time - old_sync_time).total_seconds())
                    
                    if time_diff <= 1:  # Cùng thời gian
                        logger.warning(f"⏭️ Mã {code} đã được đồng bộ cùng thời gian, từ chối")
                        rejected += 1
                        continue
                    else:
                        logger.info(f"✅ Mã {code} đã được đồng bộ ở thời gian khác, vẫn cho phép")
                
                # === TÌM HOẶC TẠO USER ===
                user = get_or_create_user(user_id, username)
                
                # === TẠO GIAO DỊCH MỚI ===
                new_trans = Transaction(
                    user_id=user.id,
                    amount=amount,
                    type='deposit',
                    status='pending',
                    transaction_code=code,
                    description=f"Auto-synced: {code}",
                    created_at=trans_time  # Dùng thời gian gốc
                )
                db.session.add(new_trans)
                
                # === LƯU VÀO BẢNG SYNCED ===
                sync_record = SyncedTransaction(
                    transaction_code=code,
                    user_id=user_id,
                    amount=amount,
                    source='daemon',
                    transaction_time=trans_time
                )
                db.session.add(sync_record)
                
                synced += 1
                logger.info(f"✅ Đồng bộ giao dịch {code} cho user {user.user_id} (thời gian: {trans_time})")
            
            db.session.commit()
            
            return jsonify({
                "success": True,
                "synced": synced,
                "skipped": skipped,
                "rejected": rejected,
                "total": len(transactions)
            }), 200
            
    except Exception as e:
        logger.error(f"❌ Lỗi đồng bộ: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 3: LẤY DANH SÁCH PENDING TRÊN RENDER =====
@app.route('/api/get-pending', methods=['GET'])
def api_get_pending():
    try:
        with app.app_context():
            pending = Transaction.query.filter_by(status='pending').all()
            result = []
            for trans in pending:
                user = User.query.get(trans.user_id)
                if user:
                    result.append({
                        "code": trans.transaction_code,
                        "amount": trans.amount,
                        "user_id": user.user_id,
                        "status": trans.status,
                        "created_at": trans.created_at.isoformat() if trans.created_at else None
                    })
            
            return jsonify({
                "success": True,
                "count": len(result),
                "transactions": result
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 4: KIỂM TRA USER =====
@app.route('/api/check-user', methods=['POST'])
def api_check_user():
    try:
        data = request.json
        user_id = data.get('user_id')
        username = data.get('username', f"user_{user_id}")
        
        with app.app_context():
            user = get_or_create_user(user_id, username)
            
            return jsonify({
                "success": True,
                "exists": True,
                "user_id": user.user_id,
                "username": user.username,
                "balance": user.balance,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }), 200
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 5: LẤY TẤT CẢ GIAO DỊCH CỦA USER =====
@app.route('/api/user-transactions', methods=['POST'])
def api_user_transactions():
    try:
        data = request.json
        user_id = data.get('user_id')
        limit = data.get('limit', 10)
        
        with app.app_context():
            user = User.query.filter_by(user_id=user_id).first()
            if not user:
                return jsonify({
                    "success": True,
                    "exists": False,
                    "message": "User not found"
                }), 200
            
            transactions = Transaction.query.filter_by(user_id=user.id).order_by(
                Transaction.created_at.desc()
            ).limit(limit).all()
            
            result = []
            for trans in transactions:
                result.append({
                    "code": trans.transaction_code,
                    "amount": trans.amount,
                    "type": trans.type,
                    "status": trans.status,
                    "created_at": trans.created_at.isoformat() if trans.created_at else None
                })
            
            return jsonify({
                "success": True,
                "user_id": user.user_id,
                "username": user.username,
                "balance": user.balance,
                "transactions": result
            }), 200
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 6: CẬP NHẬT USER =====
@app.route('/api/update-user', methods=['POST'])
def api_update_user():
    try:
        data = request.json
        user_id = data.get('user_id')
        username = data.get('username')
        
        with app.app_context():
            user = get_or_create_user(user_id)
            if username:
                user.username = username
                user.last_active = get_vn_time()
                db.session.commit()
                logger.info(f"📝 Đã cập nhật username cho user {user_id}: {username}")
            
            return jsonify({
                "success": True,
                "user_id": user.user_id,
                "username": user.username,
                "balance": user.balance
            }), 200
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 7: THỐNG KÊ HỆ THỐNG =====
@app.route('/api/stats', methods=['GET'])
def api_stats():
    try:
        with app.app_context():
            total_users = User.query.count()
            total_transactions = Transaction.query.count()
            pending_transactions = Transaction.query.filter_by(status='pending').count()
            success_transactions = Transaction.query.filter_by(status='success').count()
            total_deposits = db.session.query(db.func.sum(Transaction.amount)).filter(
                Transaction.status == 'success'
            ).scalar() or 0
            
            return jsonify({
                "success": True,
                "stats": {
                    "total_users": total_users,
                    "total_transactions": total_transactions,
                    "pending_transactions": pending_transactions,
                    "success_transactions": success_transactions,
                    "total_deposits": total_deposits,
                    "timestamp": get_vn_time().isoformat()
                }
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 8: FORCE XỬ LÝ GIAO DỊCH =====
@app.route('/api/process-transaction', methods=['POST'])
def api_process_transaction():
    try:
        data = request.json
        code = data.get('code')
        amount = data.get('amount')
        user_id = data.get('user_id')
        
        with app.app_context():
            user = get_or_create_user(user_id)
            transaction = Transaction.query.filter_by(transaction_code=code).first()
            
            if not transaction:
                transaction = Transaction(
                    user_id=user.id,
                    amount=amount,
                    type='deposit',
                    status='success',
                    transaction_code=code,
                    description=f"Force processed: {code}",
                    created_at=get_vn_time(),
                    updated_at=get_vn_time()
                )
                db.session.add(transaction)
            else:
                transaction.status = 'success'
                transaction.updated_at = get_vn_time()
            
            old_balance = user.balance
            user.balance += amount
            db.session.commit()
            
            logger.info(f"⚡ FORCE XỬ LÝ: {code} - {amount}đ cho user {user_id}")
            
            return jsonify({
                "success": True,
                "code": code,
                "amount": amount,
                "old_balance": old_balance,
                "new_balance": user.balance
            }), 200
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 9: RESET CACHE =====
@app.route('/api/reset-cache', methods=['POST'])
def api_reset_cache():
    global user_cache
    try:
        user_cache = {}
        logger.info("🔄 Đã reset user cache")
        return jsonify({"success": True, "message": "Cache reset"}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
# ===== API 10: ĐỒNG BỘ 2 CHIỀU =====
@app.route('/api/sync-bidirectional', methods=['POST'])
def api_sync_bidirectional():
    try:
        data = request.json
        logger.info(f"📥 Sync bidirectional request: {data}")
        
        # ===== LẤY DỮ LIỆU TỪ REQUEST =====
        local_transactions = data.get('local_transactions', [])
        user_id = data.get('user_id')
        balance = data.get('balance')
        username = data.get('username')
        
        with app.app_context():
            # ===== BƯỚC 1: XỬ LÝ UPDATE BALANCE (NẾU CÓ) =====
            user = None
            balance_updated = False
            
            if user_id and balance is not None:
                user = get_or_create_user(user_id, username)
                old_balance = user.balance
                
                # CHỈ CẬP NHẬT KHI BALANCE MỚI CAO HƠN HOẶC KHÁC
                if balance != old_balance:
                    # Nếu balance mới cao hơn hoặc thấp hơn đều cập nhật
                    # (Render là nguồn chính)
                    user.balance = balance
                    user.last_active = get_vn_time()
                    
                    if username:
                        user.username = username
                    
                    db.session.flush()
                    balance_updated = True
                    
                    diff = balance - old_balance
                    if diff > 0:
                        logger.info(f"💰 Cập nhật balance: +{diff}đ (User {user_id}: {old_balance} → {balance})")
                    else:
                        logger.info(f"💰 Cập nhật balance: {diff}đ (User {user_id}: {old_balance} → {balance})")
            
            # ===== BƯỚC 2: XỬ LÝ LOCAL TRANSACTIONS =====
            synced_from_local = 0
            render_pending = Transaction.query.filter_by(status='pending').all()
            render_codes = {t.transaction_code for t in render_pending}
            local_codes = set()
            
            for lt in local_transactions:
                local_codes.add(lt['code'])
                
                # Kiểm tra transaction đã tồn tại chưa
                existing = Transaction.query.filter_by(transaction_code=lt['code']).first()
                if not existing:
                    # Tìm user cho transaction này
                    trans_user = None
                    if user and user.user_id == lt['user_id']:
                        trans_user = user
                    else:
                        trans_user = get_or_create_user(lt['user_id'], lt.get('username'))
                    
                    if trans_user:
                        # Tạo transaction mới
                        new_trans = Transaction(
                            user_id=trans_user.id,
                            amount=lt['amount'],
                            type='deposit',
                            status='pending',
                            transaction_code=lt['code'],
                            description=f"Bidirectional sync: {lt['code']}",
                            created_at=get_vn_time()
                        )
                        db.session.add(new_trans)
                        synced_from_local += 1
                        logger.info(f"✅ Đồng bộ transaction từ local: {lt['code']} - {lt['amount']}đ")
            
            # ===== BƯỚC 3: CHUẨN BỊ DỮ LIỆU ĐỂ GỬI VỀ LOCAL =====
            sync_to_local = []
            for trans in render_pending:
                if trans.transaction_code not in local_codes:
                    trans_user = User.query.get(trans.user_id)
                    if trans_user:
                        sync_to_local.append({
                            "code": trans.transaction_code,
                            "amount": trans.amount,
                            "user_id": trans_user.user_id,
                            "username": trans_user.username,
                            "status": trans.status,
                            "created_at": trans.created_at.isoformat() if trans.created_at else None
                        })
            
            # ===== BƯỚC 4: COMMIT TẤT CẢ =====
            db.session.commit()
            
            # ===== BƯỚC 5: TRẢ KẾT QUẢ =====
            response_data = {
                "success": True,
                "synced_from_local": synced_from_local,
                "sync_to_local": sync_to_local,
                "render_pending_count": len(render_pending)
            }
            
            if balance_updated and user:
                response_data["balance_updated"] = True
                response_data["user_id"] = user.user_id
                response_data["new_balance"] = user.balance
            
            logger.info(f"✅ Sync bidirectional hoàn tất: {synced_from_local} transactions từ local")
            return jsonify(response_data), 200
            
    except Exception as e:
        logger.error(f"❌ Lỗi sync bidirectional: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
# ===== API 11: FORCE ĐỒNG BỘ USER =====
@app.route('/api/force-sync-user', methods=['POST'])
def api_force_sync_user():
    try:
        data = request.json
        user_id = data.get('user_id')
        
        with app.app_context():
            user = User.query.filter_by(user_id=user_id).first()
            if not user:
                return jsonify({"success": False, "error": "User not found"}), 404
            
            transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).all()
            
            result = []
            for trans in transactions:
                result.append({
                    "code": trans.transaction_code,
                    "amount": trans.amount,
                    "status": trans.status,
                    "created_at": trans.created_at.isoformat() if trans.created_at else None,
                    "updated_at": trans.updated_at.isoformat() if trans.updated_at else None
                })
            
            return jsonify({
                "success": True,
                "user_id": user.user_id,
                "username": user.username,
                "balance": user.balance,
                "transactions": result
            }), 200
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== API 12: ĐỒNG BỘ TỰ ĐỘNG 2 CHIỀU =====
@app.route('/api/auto-sync', methods=['GET'])
def api_auto_sync():
    """API tự động đồng bộ - Render tự pull dữ liệu từ local (nếu local có API)"""
    try:
        with app.app_context():
            pending = Transaction.query.filter_by(status='pending').all()
            result = []
            for trans in pending:
                user = User.query.get(trans.user_id)
                if user:
                    result.append({
                        "code": trans.transaction_code,
                        "amount": trans.amount,
                        "user_id": user.user_id,
                        "status": trans.status,
                        "created_at": trans.created_at.isoformat() if trans.created_at else None
                    })
            
            return jsonify({
                "success": True,
                "count": len(result),
                "transactions": result,
                "timestamp": get_vn_time().isoformat()
            }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ===== HÀM TỰ ĐỘNG KIỂM TRA GIAO DỊCH MỚI =====
def auto_check_new_transactions():
    global last_check_time, processed_transactions
    
    with app.app_context():
        try:
            new_transactions = Transaction.query.filter(
                Transaction.status == 'success',
                Transaction.updated_at > last_check_time
            ).all()
            
            if new_transactions:
                logger.info(f"🔍 Phát hiện {len(new_transactions)} giao dịch thành công mới")
                
                for trans in new_transactions:
                    if trans.id in processed_transactions:
                        continue
                        
                    user = User.query.get(trans.user_id)
                    if user and BOT_TOKEN:
                        try:
                            bot = Bot(token=BOT_TOKEN)
                            message = (
                                f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                                f"• **Số tiền:** `{trans.amount:,}đ`\n"
                                f"• **Mã GD:** `{trans.transaction_code}`\n"
                                f"• **Số dư mới:** `{user.balance:,}đ`\n"
                                f"• **Thời gian:** `{trans.updated_at.strftime('%H:%M:%S %d/%m/%Y')}`"
                            )
                            asyncio.run(send_telegram_message(user.user_id, message))
                            processed_transactions.add(trans.id)
                            logger.info(f"✅ Đã gửi thông báo {trans.transaction_code}")
                        except Exception as e:
                            logger.error(f"❌ Lỗi gửi Telegram: {e}")
                
                if len(processed_transactions) > 1000:
                    processed_transactions = set(list(processed_transactions)[-500:])
            
            last_check_time = get_vn_time()
            
        except Exception as e:
            logger.error(f"Lỗi auto check: {e}")

async def send_telegram_message(chat_id, message):
    if not BOT_TOKEN:
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Lỗi gửi Telegram: {e}")

# ===== THIẾT LẬP SCHEDULER =====
scheduler = BackgroundScheduler()
scheduler.start()

scheduler.add_job(
    func=check_expired_rentals,
    trigger=IntervalTrigger(minutes=10),
    id='check_expired_rentals',
    name='Kiểm tra số hết hạn',
    replace_existing=True
)

scheduler.add_job(
    func=auto_check_new_transactions,
    trigger='interval',  # ĐỔI thành string
    seconds=10,  # Thêm tham số này
    id='auto_check_new_transactions',
    name='Kiểm tra giao dịch mới',
    replace_existing=True,
    misfire_grace_time=30
)
atexit.register(lambda: scheduler.shutdown())

# ===== KHỞI ĐỘNG BACKUP THREAD =====
backup_thread = threading.Thread(target=auto_backup_loop, daemon=True)
backup_thread.start()
logger.info(f"🔄 Backup tự động mỗi {BACKUP_INTERVAL} giây - Lưu tại {BACKUP_FOLDER}/")

logger.info("="*60)
logger.info("🚀 HỆ THỐNG ĐÃ KHỞI ĐỘNG VỚI 12 API:")
logger.info("  1. POST /api/check-transaction - Kiểm tra giao dịch")
logger.info("  2. POST /api/sync-pending - Đồng bộ pending từ local")
logger.info("  3. GET  /api/get-pending - Lấy pending trên Render")
logger.info("  4. POST /api/check-user - Kiểm tra/tạo user")
logger.info("  5. POST /api/user-transactions - Lịch sử giao dịch user")
logger.info("  6. POST /api/update-user - Cập nhật user")
logger.info("  7. GET  /api/stats - Thống kê hệ thống")
logger.info("  8. POST /api/process-transaction - Force xử lý giao dịch")
logger.info("  9. POST /api/reset-cache - Reset cache")
logger.info(" 10. POST /api/sync-bidirectional - Đồng bộ 2 chiều")
logger.info(" 11. POST /api/force-sync-user - Force đồng bộ user")
logger.info(" 12. GET  /api/auto-sync - Đồng bộ tự động")
logger.info("="*60)
logger.info("⏱️  Auto check giao dịch mới: 10 giây/lần")
logger.info("⏱️  Auto check số hết hạn: 5 phút/lần")
logger.info("🔄 Backup tự động: 60 giây/lần - Giữ 50 bản gần nhất")
logger.info("="*60)

if __name__ == '__main__':
    import threading
    
    port = int(os.getenv('PORT', 10000))
    
    flask_thread = threading.Thread(
        target=lambda: app.run(
            host='0.0.0.0', 
            port=port, 
            debug=False, 
            use_reloader=False,
            threaded=True
        )
    )
    flask_thread.daemon = True
    flask_thread.start()

    logger.info(f"🌐 Flask server đang chạy trên port {port}")
    logger.info("🚫 Bot Telegram ĐÃ TẮT trên Render - Chỉ chạy local")
    logger.info("📱 Để chạy bot, gõ: python bot.py ở local")
    logger.info("📝 Lệnh kiểm tra giao dịch: /check MÃ_GD")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("👋 Đã dừng Flask server")