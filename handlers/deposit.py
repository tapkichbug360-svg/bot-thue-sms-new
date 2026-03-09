from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import CallbackContext as Context
from database.models import User, db  # Bỏ Transaction
from datetime import datetime
import logging
import random
import string
import os
import asyncio
import requests
import urllib.parse
import json  # Thêm import json
from database.models import PushedTransaction, DepositTransaction
from handlers.sync_manager import SyncManager
# Đầu file, thêm imports
from datetime import datetime, timedelta, timezone

# Thêm sau imports
VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

# Logger phải đặt ở đây trước khi dùng
logger = logging.getLogger(__name__)

pushed_transactions = set()

def generate_unique_code():
    """Tạo mã giao dịch duy nhất"""
    from database.models import DepositTransaction
    
    with app.app_context():
        while True:
            random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
            code = f"NAP{random_str}"
            
            existing = DepositTransaction.query.filter_by(
                transaction_id=code
            ).first()
            
            if not existing:
                return code
            
            logger.warning(f"⚠️ Mã {code} đã tồn tại, tạo lại...")

# ========== CẤU HÌNH ==========
MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
MB_BIN = os.getenv('MB_BIN', '970422')
RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-v2.onrender.com')

# ========== HÀM PUSH ==========
async def push_user_to_render(user_id, username, max_retries=3):
    """Đẩy user lên Render - CÓ RETRY KHI TIMEOUT"""
    for attempt in range(max_retries):
        try:
            logger.info(f"📤 Đang push user {user_id} lên Render (lần {attempt+1}/{max_retries})")
            
            response = requests.post(
                f"{RENDER_URL}/api/check-user",
                json={'user_id': user_id, 'username': username},
                timeout=30  # Tăng timeout lên 30 giây
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Đã push user {user_id} lên Render thành công")
                return True
            else:
                logger.warning(f"⚠️ Push user {user_id} thất bại: {response.status_code}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"⏰ Timeout push user {user_id} (lần {attempt+1}) - Render đang ngủ?")
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"🔌 Lỗi kết nối user {user_id} (lần {attempt+1}): {e}")
        except Exception as e:
            logger.error(f"❌ Lỗi push user {user_id} (lần {attempt+1}): {e}")
        
        # Chờ trước khi retry (exponential backoff)
        if attempt < max_retries - 1:
            wait_time = 5 * (2 ** attempt)  # 5s, 10s, 20s
            logger.info(f"⏳ Chờ {wait_time}s trước khi retry user {user_id}...")
            await asyncio.sleep(wait_time)
    
    logger.error(f"❌ Push user {user_id} thất bại sau {max_retries} lần thử")
    return False

async def push_transaction_to_render(transaction_code, amount, user_id, username):
    """Đẩy giao dịch lên Render - CHỈ PUSH GIAO DỊCH MỚI (dưới 5 phút)"""
    global pushed_transactions
    
    # Kiểm tra cache
    if transaction_code in pushed_transactions:
        logger.info(f"ℹ️ GD {transaction_code} đã push (cache)")
        return True
    
    # Kiểm tra database
    with app.app_context():
        from database.models import PushedTransaction, DepositTransaction
        
        db_pushed = PushedTransaction.query.filter_by(
            transaction_code=transaction_code
        ).first()
        if db_pushed:
            logger.info(f"ℹ️ GD {transaction_code} đã push (database)")
            pushed_transactions.add(transaction_code)
            return True
        
        # ==== KIỂM TRA THỜI GIAN - CHỈ PUSH GIAO DỊCH TRONG 5 PHÚT ====
        transaction = DepositTransaction.query.filter_by(
            transaction_id=transaction_code
        ).first()
        
        if transaction:
            time_diff = datetime.now() - transaction.created_at
            if time_diff.total_seconds() > 300:  # Quá 5 phút
                logger.info(f"⏰ GD {transaction_code} cũ ({int(time_diff.total_seconds())}s), đánh dấu đã push")
                # Đánh dấu là đã push để không xử lý lại
                pushed = PushedTransaction(transaction_code=transaction_code)
                db.session.add(pushed)
                db.session.commit()
                pushed_transactions.add(transaction_code)
                return True
    
    # Thử push lên Render (với timeout ngắn)
    try:
        logger.info(f"📤 Push GD {transaction_code} lên Render")
        response = requests.post(
            f"{RENDER_URL}/api/sync-pending",
            json={'transactions': [{
                'code': transaction_code,
                'amount': amount,
                'user_id': user_id,
                'username': username
            }]},
            timeout=5
        )
        
        if response.status_code == 200:
            # Lưu vào database
            with app.app_context():
                pushed = PushedTransaction(transaction_code=transaction_code)
                db.session.add(pushed)
                db.session.commit()
            
            pushed_transactions.add(transaction_code)
            logger.info(f"✅ Push GD {transaction_code} thành công")
            return True
        else:
            logger.warning(f"⚠️ Push GD {transaction_code} thất bại: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"⏰ Timeout push GD {transaction_code}")
        return False
    except Exception as e:
        logger.error(f"❌ Lỗi push GD {transaction_code}: {e}")
        return False
async def check_render_alive():
    """Kiểm tra Render server còn hoạt động không"""
    try:
        response = requests.get(
            f"{RENDER_URL}/api/health",
            timeout=10
        )
        return response.status_code == 200
    except:
        return False

async def sync_all_users_with_retry():
    """Đồng bộ tất cả users khi khởi động - CÓ RETRY"""
    logger.info("🔄 Đang đồng bộ users với Render...")
    
    # Kiểm tra Render còn sống không
    if not await check_render_alive():
        logger.warning("⚠️ Render không phản hồi, sẽ thử lại sau 60s")
        return False
    
    with app.app_context():
        users = User.query.all()
        logger.info(f"📋 Local có {len(users)} user")
        
        success = 0
        failed = 0
        
        for user in users:
            username = user.username or f"user_{user.user_id}"
            if await push_user_to_render(user.user_id, username):
                success += 1
            else:
                failed += 1
            
            # Không spam request
            await asyncio.sleep(0.5)
        
        logger.info(f"✅ Đồng bộ xong: {success} thành công, {failed} thất bại")
        return failed == 0

async def push_transaction_with_retry(transaction_code, amount, user_id, username, max_retries=3):
    """Push transaction với cơ chế retry"""
    for attempt in range(max_retries):
        try:
            success = await push_transaction_to_render(transaction_code, amount, user_id, username)
            if success:
                return True
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"⏳ Chờ {wait_time}s trước khi retry GD {transaction_code}...")
                await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"❌ Lỗi push GD {transaction_code} (lần {attempt+1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    logger.error(f"❌ Push GD {transaction_code} thất bại sau {max_retries} lần thử")
    return False

# ========== HANDLERS ==========
async def deposit_command(update: Update, context: Context):
    """Hiển thị menu nạp tiền"""
    logger.info("💰 deposit_command được gọi")
    
    # Xóa menu cũ nếu có - NHƯNG BẮT LỖI
    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.delete()
    except Exception as e:
        logger.error(f"Lỗi xóa menu cũ: {e}")
        # Không sao, tiếp tục
    
    transaction_code = generate_unique_code()
    context.user_data['pending_deposit'] = {
        'code': transaction_code,
        'amount': None,
        'created_at': datetime.now().isoformat()
    }
    
    logger.info(f"📝 Tạo mã GD mới: {transaction_code} cho user {update.effective_user.id}")
    
    amounts = [20000, 50000, 100000, 200000, 500000, 1000000]
    keyboard = []
    row = []
    for i, amount in enumerate(amounts):
        btn = InlineKeyboardButton(f"{amount:,}đ", callback_data=f"deposit_amount_{amount}")
        row.append(btn)
        if len(row) == 2 or i == len(amounts)-1:
            keyboard.append(row)
            row = []
    
    keyboard.append([InlineKeyboardButton("🔙 Quay lại menu chính", callback_data="menu_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""💳 **NẠP TIỀN QUA MBBANK**

🏦 **Số TK:** `{MB_ACCOUNT}`
👤 **Chủ TK:** {MB_NAME}
🏛️ **Ngân hàng:** MBBank

📝 **Nội dung chuyển khoản:** `NAP {transaction_code}`

⚠️ **Lưu ý quan trọng:**
• Ghi đúng nội dung để được cộng tiền tự động
• Tiền sẽ được cộng trong 1-5 phút sau khi chuyển
• Nếu quá 10 phút, liên hệ admin với mã GD

💰 **Chọn số tiền muốn nạp:**"""
    
    # Gửi tin nhắn - KHÔNG EDIT, LUÔN GỬI MỚI
    if update.callback_query:
        try:
            # Thử edit nếu message còn
            await update.callback_query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Không thể edit message, gửi tin nhắn mới: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )

async def deposit_amount_callback(update: Update, context: Context):
    """Xử lý khi chọn số tiền"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    
    try:
        amount = int(query.data.split('_')[2])
        pending = context.user_data.get('pending_deposit', {})
        transaction_code = pending.get('code')
        
        if not transaction_code:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text="❌ Có lỗi xảy ra! Vui lòng thử lại."
            )
            return
        
        user = update.effective_user
        username = user.username or user.first_name or f"user_{user.id}"
        
        with app.app_context():
            db_user = User.query.filter_by(user_id=user.id).first()
            if not db_user:
                db_user = User(
                    user_id=user.id,
                    username=username,
                    balance=0,
                    created_at=datetime.now()
                )
                db.session.add(db_user)
                db.session.commit()
                logger.info(f"🆕 Đã tạo user mới: {user.id}")
            
            from database.models import DepositTransaction

            # Kiểm tra transaction đã tồn tại chưa
            existing = DepositTransaction.query.filter_by(
                transaction_id=transaction_code
            ).first()
            
            if existing:
                logger.warning(f"⚠️ Mã GD {transaction_code} đã tồn tại, tạo mã mới...")
                transaction_code = generate_unique_code()
                context.user_data['pending_deposit']['code'] = transaction_code

            transaction = DepositTransaction(
                transaction_id=transaction_code,
                user_id=user.id,
                amount=amount,
                status='pending',
                created_at=datetime.now(),
                webhook_data=json.dumps({
                    'source': 'telegram',
                    'username': username,
                    'chat_id': update.effective_chat.id,
                    'created_at': datetime.now().isoformat()
                })
            )
            db.session.add(transaction)
            db.session.commit()
            
            logger.info(f"✅ ĐÃ TẠO GIAO DỊCH: {transaction_code} - {amount}đ cho user {user.id}")
        
        # Push lên Render
        await asyncio.gather(
            push_user_to_render(user.id, username),
            push_transaction_to_render(transaction_code, amount, user.id, username)
        )
        
        content = f"NAP {transaction_code}"
        encoded_content = urllib.parse.quote(content)
        qr_url = f"https://img.vietqr.io/image/{MB_BIN}-{MB_ACCOUNT}-compact2.jpg?amount={amount}&addInfo={encoded_content}&accountName={MB_NAME}"
        
        keyboard = [
            [InlineKeyboardButton("✅ TÔI ĐÃ CHUYỂN KHOẢN", callback_data=f"deposit_check_{transaction_code}")],
            [InlineKeyboardButton("💰 Nạp số khác", callback_data="menu_deposit")],
            [InlineKeyboardButton("📱 Thuê số", callback_data="menu_rent")],
            [InlineKeyboardButton("🔙 Menu chính", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=qr_url,
            caption=f"""📌 **THÔNG TIN CHUYỂN KHOẢN**

🏦 **STK:** `{MB_ACCOUNT}`
👤 **Chủ TK:** {MB_NAME}
💰 **Số tiền:** {amount:,}đ
📝 **Nội dung:** `{content}`

🆔 **Mã GD:** `{transaction_code}`

👇 **Bấm nút 'TÔI ĐÃ CHUYỂN KHOẢN' sau khi chuyển!""",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        await query.delete_message()
        
    except Exception as e:
        logger.error(f"❌ Lỗi deposit_amount_callback: {e}")
        import traceback
        traceback.print_exc()
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="❌ Có lỗi xảy ra! Vui lòng thử lại."
        )

async def deposit_check_callback(update: Update, context: Context):
    """Xử lý khi user bấm 'TÔI ĐÃ CHUYỂN KHOẢN' - CHỐNG SPAM"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    
    try:
        transaction_code = query.data.split('_')[2]
        logger.info(f"💰 User báo đã chuyển khoản - Mã GD: {transaction_code}")
        
        with app.app_context():
            from database.models import DepositTransaction, User
            
            transaction = DepositTransaction.query.filter_by(
                transaction_id=transaction_code
            ).first()
            
            if not transaction:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ **KHÔNG TÌM THẤY GIAO DỊCH**\n\nMã GD: {transaction_code}",
                    parse_mode='Markdown'
                )
                return
            
            # ==== KIỂM TRA THỜI GIAN - CHỐNG SPAM ====
            time_diff = datetime.now() - transaction.created_at
            minutes_diff = int(time_diff.total_seconds() / 60)
            
            # Nếu giao dịch quá 30 phút
            if minutes_diff > 30:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⏰ **GIAO DỊCH ĐÃ QUÁ HẠN**\n\n"
                         f"📝 Mã GD: `{transaction_code}`\n"
                         f"💰 Số tiền: {transaction.amount:,}đ\n"
                         f"⏱️ Tạo lúc: {transaction.created_at.strftime('%H:%M:%S')}\n"
                         f"⏰ Đã qua {minutes_diff} phút\n\n"
                         f"❌ Vui lòng tạo giao dịch mới để được hỗ trợ.",
                    parse_mode='Markdown'
                )
                return
            
            # Nếu giao dịch đã hoàn thành
            if transaction.status == 'completed':
                user = User.query.filter_by(user_id=transaction.user_id).first()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ **GIAO DỊCH ĐÃ HOÀN TẤT**\n\n"
                         f"📝 Mã GD: `{transaction_code}`\n"
                         f"💰 Số tiền: {transaction.amount:,}đ\n"
                         f"💵 Số dư hiện tại: {user.balance:,}đ\n"
                         f"⏱️ Xử lý lúc: {transaction.processed_at.strftime('%H:%M:%S')}",
                    parse_mode='Markdown'
                )
                return
            
            # Nếu giao dịch đã hết hạn
            if transaction.status == 'expired':
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⏰ **GIAO DỊCH ĐÃ HẾT HẠN**\n\n"
                         f"📝 Mã GD: `{transaction_code}`\n"
                         f"💰 Số tiền: {transaction.amount:,}đ\n\n"
                         f"❌ Vui lòng tạo giao dịch mới.",
                    parse_mode='Markdown'
                )
                return
            
            # Còn pending và trong thời gian cho phép
            if minutes_diff < 30:
                # Cập nhật thời gian
                if hasattr(transaction, 'updated_at'):
                    transaction.updated_at = datetime.now()
                db.session.commit()
                
                # Gửi thông báo chờ
                text = f"""⏳ **ĐANG XỬ LÝ GIAO DỊCH**

💰 **Số tiền:** {transaction.amount:,}đ
📝 **Mã GD:** `{transaction_code}`
⏱️ **Thời gian:** {minutes_diff} phút trước

✅ **Đã ghi nhận yêu cầu nạp tiền của bạn.**

🤖 **Hệ thống đang chờ xác nhận từ ngân hàng.**
⏰ **Tiền sẽ được cộng tự động trong 1-5 phút.**

⚠️ **LƯU Ý:**
• Không cần bấm nút nhiều lần
• Nếu quá 10 phút, liên hệ admin với mã GD"""
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    parse_mode='Markdown'
                )
            else:
                # Trường hợp khác
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ **LỖI XỬ LÝ**\n\nVui lòng liên hệ admin.",
                    parse_mode='Markdown'
                )
            
    except Exception as e:
        logger.error(f"❌ Lỗi deposit_check_callback: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ **LỖI XỬ LÝ**\n\nVui lòng thử lại sau.",
            parse_mode='Markdown'
        )

async def check_deposit_status(update: Update, context: Context):
    """Lệnh kiểm tra trạng thái giao dịch thủ công"""
    try:
        if not context.args:
            await update.message.reply_text(
                "❌ **Sai cú pháp**\n\nDùng: `/check MÃ_GD`",
                parse_mode='Markdown'
            )
            return
        
        code = context.args[0].upper()
        
        try:
            response = requests.post(
                f"{RENDER_URL}/api/check-transaction",
                json={'code': code},
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('exists'):
                    status_text = {
                        'pending': '⏳ Đang chờ',
                        'success': '✅ Thành công',
                        'failed': '❌ Thất bại'
                    }.get(data['status'], '❓ Không xác định')
                    
                    with app.app_context():
                        from database.models import DepositTransaction
                        local_trans = DepositTransaction.query.filter_by(transaction_id=code).first()
                        if local_trans:
                            user = User.query.filter_by(user_id=local_trans.user_id).first()
                            local_status = local_trans.status
                            local_balance = user.balance if user else 0
                        else:
                            local_status = 'not_found'
                            local_balance = 0
                    
                    await update.message.reply_text(
                        f"🔍 **KIỂM TRA GIAO DỊCH {code}**\n\n"
                        f"🌐 **Render:** {status_text}\n"
                        f"💻 **Local:** {local_status}\n"
                        f"💰 **Số tiền:** {data['amount']:,}đ\n"
                        f"💵 **Số dư:** {local_balance:,}đ",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(f"❌ Không tìm thấy mã `{code}`")
            else:
                await update.message.reply_text("⚠️ **LỖI KẾT NỐI**")
        except Exception as e:
            logger.error(f"Lỗi check status: {e}")
            await update.message.reply_text("⚠️ **LỖI KẾT NỐI**")
            
    except Exception as e:
        logger.error(f"Lỗi check_deposit_status: {e}")
        await update.message.reply_text("⚠️ **LỖI XỬ LÝ**")