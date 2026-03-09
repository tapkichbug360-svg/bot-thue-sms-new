import logging
import os
import sys
import atexit
import asyncio
import time
import requests
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

# ===== ĐỌC BIẾN MÔI TRƯỜNG ĐƠN GIẢN =====
print("🔍 ĐANG ĐỌC BIẾN MÔI TRƯỜNG...")

BOT_TOKEN = None
API_KEY = None
BASE_URL = None
ADMIN_ID = None
MB_ACCOUNT = None
MB_NAME = None
MB_BIN = None
SEPAY_TOKEN = None
RENDER_URL = None

# Đọc từ biến môi trường hệ thống (Render)
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID')
MB_ACCOUNT = os.getenv('MB_ACCOUNT')
MB_NAME = os.getenv('MB_NAME')
MB_BIN = os.getenv('MB_BIN')
SEPAY_TOKEN = os.getenv('SEPAY_TOKEN')
RENDER_URL = os.getenv('RENDER_URL')

# Fallback: đọc từ file .env nếu chạy local
if not BOT_TOKEN and os.path.exists('.env'):
    print("📁 Đọc file .env (local mode)...")
    from dotenv import load_dotenv
    load_dotenv()
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    API_KEY = os.getenv('API_KEY')
    BASE_URL = os.getenv('BASE_URL')
    ADMIN_ID = os.getenv('ADMIN_ID')
    MB_ACCOUNT = os.getenv('MB_ACCOUNT')
    MB_NAME = os.getenv('MB_NAME')
    MB_BIN = os.getenv('MB_BIN')
    SEPAY_TOKEN = os.getenv('SEPAY_TOKEN')
    RENDER_URL = os.getenv('RENDER_URL')

# Kiểm tra biến quan trọng
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

# Kiểm tra các biến quan trọng
if not BOT_TOKEN:
    print("❌ KHÔNG TÌM THẤY BOT_TOKEN (ĐÃ THỬ 5 CÁCH)")
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
    """Kiểm tra và tự động hoàn tiền cho các số hết hạn"""
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
                    user.balance += refund
                    rental.status = 'expired'
                    rental.updated_at = get_vn_time()
                    db.session.commit()

                    logger.info(f"💰 TỰ ĐỘNG HOÀN {refund}đ CHO USER {user.user_id}")
                    
                    if BOT_TOKEN:
                        try:
                            bot = Bot(token=BOT_TOKEN)
                            message = (
                                f"⏰ **SỐ HẾT HẠN & HOÀN TIỀN**\n\n"
                                f"• **Số:** `{rental.phone_number}`\n"
                                f"• **Dịch vụ:** {rental.service_name}\n"
                                f"• **Tiền hoàn:** `{refund:,}đ`\n"
                                f"• **Số dư mới:** `{user.balance:,}đ`"
                            )
                            asyncio.run(send_telegram_message(user.user_id, message))
                        except Exception as e:
                            logger.error(f"Lỗi gửi Telegram: {e}")
        except Exception as e:
            logger.error(f"Lỗi kiểm tra số hết hạn: {e}")

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
            
            for t in transactions:
                user = get_or_create_user(t['user_id'], t.get('username'))
                
                existing = Transaction.query.filter_by(transaction_code=t['code']).first()
                if not existing:
                    new_trans = Transaction(
                        user_id=user.id,
                        amount=t['amount'],
                        type='deposit',
                        status='pending',
                        transaction_code=t['code'],
                        description=f"Auto-synced: {t['code']}",
                        created_at=get_vn_time()
                    )
                    db.session.add(new_trans)
                    synced += 1
                    logger.info(f"✅ Đồng bộ giao dịch {t['code']} cho user {user.user_id}")
                else:
                    skipped += 1
            
            db.session.commit()
            
            return jsonify({
                "success": True,
                "synced": synced,
                "skipped": skipped,
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

# ===== API 10: ĐỒNG BỘ 2 CHIỀU TỰ ĐỘNG =====
@app.route('/api/sync-bidirectional', methods=['POST'])
def api_sync_bidirectional():
    try:
        data = request.json
        local_transactions = data.get('local_transactions', [])
        
        with app.app_context():
            render_pending = Transaction.query.filter_by(status='pending').all()
            render_codes = {t.transaction_code for t in render_pending}
            
            local_codes = set()
            synced_from_local = 0
            sync_to_local = []
            
            # 1. ĐỒNG BỘ TỪ LOCAL LÊN RENDER
            for lt in local_transactions:
                local_codes.add(lt['code'])
                
                existing = Transaction.query.filter_by(transaction_code=lt['code']).first()
                if not existing:
                    user = get_or_create_user(lt['user_id'], lt.get('username'))
                    new_trans = Transaction(
                        user_id=user.id,
                        amount=lt['amount'],
                        type='deposit',
                        status='pending',
                        transaction_code=lt['code'],
                        description=f"Bidirectional sync: {lt['code']}",
                        created_at=get_vn_time()
                    )
                    db.session.add(new_trans)
                    synced_from_local += 1
                    logger.info(f"✅ Đồng bộ từ local: {lt['code']}")
            
            # 2. CHUẨN BỊ DỮ LIỆU ĐỒNG BỘ VỀ LOCAL
            for trans in render_pending:
                if trans.transaction_code not in local_codes:
                    user = User.query.get(trans.user_id)
                    if user:
                        sync_to_local.append({
                            "code": trans.transaction_code,
                            "amount": trans.amount,
                            "user_id": user.user_id,
                            "status": trans.status,
                            "created_at": trans.created_at.isoformat() if trans.created_at else None
                        })
            
            db.session.commit()
            
            return jsonify({
                "success": True,
                "synced_from_local": synced_from_local,
                "sync_to_local": sync_to_local,
                "render_pending_count": len(render_pending)
            }), 200
            
    except Exception as e:
        logger.error(f"❌ Lỗi sync bidirectional: {e}")
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
    trigger=IntervalTrigger(minutes=5),
    id='check_expired_rentals',
    name='Kiểm tra số hết hạn',
    replace_existing=True
)

scheduler.add_job(
    func=auto_check_new_transactions,
    trigger=IntervalTrigger(seconds=10),
    id='auto_check_new_transactions',
    name='Kiểm tra giao dịch mới',
    replace_existing=True
)

atexit.register(lambda: scheduler.shutdown())

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

