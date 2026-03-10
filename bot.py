import logging
import os
import sys
import asyncio
import signal
import psutil
import requests
from datetime import datetime, timedelta, timezone
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import Bot
from telegram.request import HTTPXRequest
from flask import Flask
from database.models import db, User, Transaction, DepositTransaction, PushedTransaction
from dotenv import load_dotenv
from apscheduler.triggers.interval import IntervalTrigger

# ==================== CẤU HÌNH LOGGING ====================
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
logging.getLogger('apscheduler.scheduler').setLevel(logging.WARNING)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== MÚI GIỜ ====================
VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

# ==================== ĐỌC BIẾN MÔI TRƯỜNG ====================
print("📁 Đang đọc file .env...")
load_dotenv()  # Tự động đọc file .env

BOT_TOKEN = os.getenv('BOT_TOKEN')
API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID')
MB_ACCOUNT = os.getenv('MB_ACCOUNT')
MB_NAME = os.getenv('MB_NAME')
RENDER_URL = os.getenv('RENDER_URL')

# In ra để kiểm tra (ẩn 1 phần)
print(f"   ✅ BOT_TOKEN: {BOT_TOKEN[:10] if BOT_TOKEN else 'None'}...")
print(f"   ✅ API_KEY: {API_KEY[:10] if API_KEY else 'None'}...")
print(f"   ✅ BASE_URL: {BASE_URL}")
print(f"   ✅ RENDER_URL: {RENDER_URL}")
print(f"🔍 BOT DÙNG DATABASE: {os.path.abspath('database/bot.db')}")

# Kiểm tra biến quan trọng
if not BOT_TOKEN:
    print("❌ KHÔNG TÌM THẤY BOT_TOKEN")
    sys.exit(1)
if not API_KEY:
    print("❌ KHÔNG TÌM THẤY API_KEY")
    sys.exit(1)
if not BASE_URL:
    print("❌ KHÔNG TÌM THẤY BASE_URL")
    sys.exit(1)

print("✅ Đã đọc tất cả biến môi trường thành công!")

# ==================== DATABASE ====================
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'database', 'bot.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
logger.info(f"✅ Database path: {db_path}")

# ==================== HÀM GỬI THÔNG BÁO TELEGRAM ====================
async def send_telegram_message(chat_id, text):
    """Gửi tin nhắn Telegram đến user"""
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Đã gửi thông báo đến user {chat_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Lỗi gửi Telegram: {e}")
        return False

# ==================== HÀM KIỂM TRA GIAO DỊCH MỚI ====================
async def check_new_transactions():
    """Kiểm tra giao dịch mới và gửi thông báo"""
    with app.app_context():
        try:
            # Lấy các giao dịch thành công trong 10 giây qua
            time_threshold = datetime.now() - timedelta(seconds=10)
            new_transactions = Transaction.query.filter(
                Transaction.status == 'success',
                Transaction.updated_at > time_threshold
            ).all()
            
            for trans in new_transactions:
                user = User.query.get(trans.user_id)
                if user:
                    # Kiểm tra xem đã gửi thông báo chưa
                    if not hasattr(trans, 'notified') or not trans.notified:
                        message = (
                            f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                            f"• **Số tiền:** `{trans.amount:,}đ`\n"
                            f"• **Mã GD:** `{trans.transaction_code}`\n"
                            f"• **Số dư mới:** `{user.balance:,}đ`\n"
                            f"• **Thời gian:** `{datetime.now().strftime('%H:%M:%S %d/%m/%Y')}`"
                        )
                        await send_telegram_message(user.user_id, message)
                        
                        # Đánh dấu đã gửi
                        trans.notified = True
                        db.session.commit()
                        logger.info(f"✅ Đã gửi thông báo GD {trans.transaction_code}")
                        
        except Exception as e:
            logger.error(f"❌ Lỗi kiểm tra giao dịch: {e}")

# ==================== IMPORT HANDLERS ====================
try:
    from handlers.start import (
        start_command, menu_command, cancel, help_command, 
        check_command, history_command, cancel_command,
        balance_command
    )
    from handlers.deposit import (
        deposit_command, deposit_amount_callback, deposit_check_callback
    )
    from handlers.rent import (
        rent_command, rent_service_callback, rent_network_callback,
        rent_confirm_callback, rent_check_callback, rent_cancel_callback,
        rent_view_callback, rent_list_callback, rent_reuse_callback
    )
    from handlers.callback import menu_callback
    logger.info("✅ Import handlers thành công")
except Exception as e:
    logger.error(f"❌ LỖI IMPORT HANDLERS: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ==================== HÀM DỌN DẸP ====================
def kill_other_instances():
    """Kill các instance bot khác đang chạy"""
    current_pid = os.getpid()
    killed = 0
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if (proc.info['pid'] != current_pid and 
                    'python' in proc.info['name'] and 
                    'bot.py' in cmdline):
                    os.kill(proc.info['pid'], signal.SIGTERM)
                    killed += 1
                    logger.info(f"✅ Đã kill instance cũ PID: {proc.info['pid']}")
            except:
                pass
    except Exception as e:
        logger.error(f"Lỗi kill: {e}")
    return killed

def cleanup_telegram():
    """Dọn dẹp kết nối Telegram cũ"""
    try:
        close_url = f"https://api.telegram.org/bot{BOT_TOKEN}/close"
        close_res = requests.post(close_url)
        logger.info(f"Close connection: {close_res.status_code}")
        
        webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
        webhook_res = requests.post(webhook_url)
        logger.info(f"Delete webhook: {webhook_res.status_code}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

async def cleanup_old_data():
    """Dọn dẹp dữ liệu cũ mỗi giờ"""
    with app.app_context():
        # Đánh dấu giao dịch pending quá 24h là expired
        old_pending = DepositTransaction.query.filter(
            DepositTransaction.status == 'pending',
            DepositTransaction.created_at < datetime.now() - timedelta(hours=24)
        ).all()
        
        for trans in old_pending:
            trans.status = 'expired'
            logger.info(f"⏰ Đánh dấu hết hạn GD cũ: {trans.transaction_id}")
        
        # Xóa pushed transaction cũ quá 7 ngày
        old_pushed = PushedTransaction.query.filter(
            PushedTransaction.pushed_at < datetime.now() - timedelta(days=7)
        ).all()
        
        for pushed in old_pushed:
            db.session.delete(pushed)
        
        if old_pending or old_pushed:
            db.session.commit()
            logger.info(f"🧹 Đã dọn dẹp: {len(old_pending)} GD pending, {len(old_pushed)} pushed cũ")

async def set_bot_commands(application):
    """Thiết lập menu commands cho bot"""
    commands = [
        ("start", "🚀 Khởi động bot"),
        ("rent", "📱 Thuê số nhận OTP"),
        ("balance", "💰 Xem số dư"),
        ("deposit", "💳 Nạp tiền"),
        ("history", "📜 Lịch sử giao dịch"),
        ("help", "❓ Hướng dẫn sử dụng"),
        ("cancel", "❌ Hủy thao tác hiện tại"),
        ("check", "🔍 Kiểm tra giao dịch (kèm mã GD)")
    ]
    
    await application.bot.set_my_commands(commands)
    logger.info("✅ Đã thiết lập menu commands")

# ==================== HÀM MAIN ====================
async def main():
    """Hàm chính khởi động bot"""
    killed = kill_other_instances()
    if killed > 0:
        logger.info(f"Đã kill {killed} instance cũ")
    cleanup_telegram()
    
    try:
        logger.info("🚀 BOT ĐANG KHỞI ĐỘNG...")
        
        # Kiểm tra database
        with app.app_context():
            try:
                db.create_all()
                user_count = User.query.count()
                logger.info(f"✅ Kết nối database thành công! Số user: {user_count}")
            except Exception as e:
                logger.error(f"❌ Lỗi kết nối database: {e}")
                sys.exit(1)
        
        # Cấu hình request với timeout dài hơn
        request = HTTPXRequest(
            connection_pool_size=20,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30
        )
        
        # Tạo application với request đã cấu hình
        application = Application.builder().token(BOT_TOKEN).request(request).build()
        
        # Thiết lập menu commands
        await set_bot_commands(application)
        
        # COMMAND HANDLERS
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("balance", balance_command))
        application.add_handler(CommandHandler("deposit", deposit_command))
        application.add_handler(CommandHandler("rent", rent_command))
        application.add_handler(CommandHandler('check', check_command))
        application.add_handler(CommandHandler('cancel', cancel_command))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('history', history_command))
        
        # CALLBACK HANDLERS
        application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
        application.add_handler(CallbackQueryHandler(deposit_amount_callback, pattern="^deposit_amount_"))
        application.add_handler(CallbackQueryHandler(deposit_check_callback, pattern="^deposit_check_"))
        application.add_handler(CallbackQueryHandler(rent_service_callback, pattern="^rent_service_"))
        application.add_handler(CallbackQueryHandler(rent_network_callback, pattern="^rent_network_"))
        application.add_handler(CallbackQueryHandler(rent_confirm_callback, pattern="^rent_confirm_"))
        application.add_handler(CallbackQueryHandler(rent_check_callback, pattern="^rent_check_"))
        application.add_handler(CallbackQueryHandler(rent_cancel_callback, pattern="^rent_cancel_"))
        application.add_handler(CallbackQueryHandler(rent_view_callback, pattern="^rent_view_"))
        application.add_handler(CallbackQueryHandler(rent_reuse_callback, pattern="^rent_reuse_"))
        application.add_handler(CallbackQueryHandler(rent_list_callback, pattern="^menu_rent_list"))
        
        logger.info("✅ BOT KHỞI ĐỘNG THÀNH CÔNG!")
        
        # Khởi động scheduler
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        
        # Thêm job dọn dẹp
        scheduler.add_job(cleanup_old_data, 'interval', hours=1)
        
        # Thêm job kiểm tra giao dịch mới (chạy mỗi 10 giây)
        scheduler.add_job(
        check_new_transactions, 
        trigger=IntervalTrigger(seconds=10, misfire_grace_time=30),  # THÊM Ở ĐÂY
        id='check_new_transactions',  # THÊM ID ĐỂ DỄ QUẢN LÝ
        misfire_grace_time=30  # HOẶC THÊM Ở ĐÂY 
        )
        
        scheduler.start()
        logger.info("✅ Scheduler started (cleanup + check transactions)")
        
        # Khởi động bot
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Giữ bot chạy
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"❌ LỖI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# ==================== CHẠY BOT ====================
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot đã dừng")
    except Exception as e:
        logger.error(f"❌ LỖI: {e}")
        import traceback
        traceback.print_exc()