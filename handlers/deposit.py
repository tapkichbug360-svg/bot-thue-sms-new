from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import CallbackContext as Context
from database.models import User, Transaction, db
from datetime import datetime
import logging
import random
import string
import os
import asyncio
import requests
import urllib.parse
import time

logger = logging.getLogger(__name__)

MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
MB_BIN = os.getenv('MB_BIN', '970422')
RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-new.onrender.com')

# Cache để tránh push trùng
pushed_transactions = set()
pushed_transactions_time = {}
CACHE_DURATION = 300  # 5 phút

# Cache menu để tối ưu
menu_cache = {}
menu_cache_time = {}
MENU_CACHE_DURATION = 300  # 5 phút

# ==================== HÀM TIỆN ÍCH ====================
async def safe_send_message(update, text, reply_markup=None, parse_mode='Markdown', max_retries=2):
    """Gửi tin nhắn an toàn, tự động retry khi timeout"""
    for attempt in range(max_retries):
        try:
            if update.callback_query:
                return await update.callback_query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            else:
                return await update.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"❌ Gửi tin nhắn thất bại: {e}")
                # Fallback: gửi tin nhắn mới
                if update.callback_query:
                    return await update.effective_chat.send_message(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
            logger.warning(f"⏰ Lần {attempt + 1} thất bại, thử lại...")
            await asyncio.sleep(1)
    return None

async def safe_answer_callback(query, text=None, show_alert=False):
    """Answer callback an toàn"""
    try:
        await query.answer(text=text, show_alert=show_alert, cache_time=0)
    except Exception as e:
        logger.debug(f"Answer callback error: {e}")

def get_cached_menu(menu_name, create_func):
    """Lấy menu từ cache"""
    now = time.time()
    if menu_name in menu_cache and now - menu_cache_time.get(menu_name, 0) < MENU_CACHE_DURATION:
        return menu_cache[menu_name]
    
    menu = create_func()
    menu_cache[menu_name] = menu
    menu_cache_time[menu_name] = now
    return menu

def create_deposit_amount_menu():
    """Tạo menu chọn số tiền"""
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
    return InlineKeyboardMarkup(keyboard)

# Cache menu chọn tiền
deposit_amount_menu = create_deposit_amount_menu()

# ==================== HÀM PUSH LÊN RENDER ====================
async def push_user_to_render(user_id, username):
    """Đẩy user lên Render ngay lập tức"""
    try:
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id, 'username': username},
            timeout=5
        )
        if response.status_code == 200:
            logger.info(f"✅ Đã push user {user_id} lên Render")
            return True
        else:
            logger.warning(f"⚠️ Push user {user_id} thất bại: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Lỗi push user {user_id}: {e}")
        return False

async def push_transaction_to_render(transaction_code, amount, user_id, username):
    """Đẩy giao dịch lên Render ngay sau khi tạo"""
    global pushed_transactions, pushed_transactions_time
    
    # Kiểm tra cache tránh push trùng
    now = time.time()
    if transaction_code in pushed_transactions:
        last_push = pushed_transactions_time.get(transaction_code, 0)
        if now - last_push < CACHE_DURATION:
            logger.info(f"ℹ️ Giao dịch {transaction_code} đã được push gần đây")
            return True
    
    try:
        response = requests.post(
            f"{RENDER_URL}/api/sync-pending",
            json={
                'transactions': [{
                    'code': transaction_code,
                    'amount': amount,
                    'user_id': user_id,
                    'username': username,
                    'created_at': datetime.now().isoformat()
                }]
            },
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Đã push giao dịch {transaction_code} lên Render")
            
            # Lưu vào cache
            pushed_transactions.add(transaction_code)
            pushed_transactions_time[transaction_code] = now
            
            # Giới hạn cache
            if len(pushed_transactions) > 100:
                pushed_transactions.clear()
                pushed_transactions_time.clear()
            
            return True
        else:
            logger.warning(f"⚠️ Push giao dịch {transaction_code} thất bại: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Lỗi push giao dịch {transaction_code}: {e}")
        return False

# ==================== COMMAND CHÍNH ====================
async def deposit_command(update: Update, context: Context):
    """Hiển thị menu nạp tiền - SIÊU MƯỢT"""
    # Answer ngay để chống lag
    if update.callback_query:
        await safe_answer_callback(update.callback_query, "🔄 Đang tải...")
    
    # Tạo mã giao dịch
    transaction_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    context.user_data['pending_deposit'] = {'code': transaction_code, 'amount': None}
    
    text = f"""💳 **NẠP TIỀN QUA MBBANK**

🏦 **Số TK:** `{MB_ACCOUNT}`
👤 **Chủ TK:** {MB_NAME}
🏛️ **Ngân hàng:** MBBank

📝 **Nội dung:** NAP {transaction_code}

💰 **Chọn số tiền:**"""
    
    await safe_send_message(update, text, deposit_amount_menu)

async def deposit_amount_callback(update: Update, context: Context):
    """Xử lý khi chọn số tiền - TỐI ƯU HÓA"""
    query = update.callback_query
    await safe_answer_callback(query, "⏳ Đang xử lý...")
    
    try:
        amount = int(query.data.split('_')[2])
        pending = context.user_data.get('pending_deposit', {})
        transaction_code = pending.get('code')
        
        if not transaction_code:
            await safe_send_message(update, "❌ Có lỗi xảy ra! Vui lòng thử lại.")
            return
        
        user = update.effective_user
        username = user.username or user.first_name or f"user_{user.id}"
        
        # Hiển thị loading
        loading_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔄 **Đang tạo giao dịch...**",
            parse_mode='Markdown'
        )
        
        # Lưu giao dịch vào database local
        with app.app_context():
            # Tìm hoặc tạo user
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
            
            # Tạo transaction pending
            transaction = Transaction(
                user_id=db_user.id,
                amount=amount,
                type='deposit',
                status='pending',
                transaction_code=transaction_code,
                description=f'Nạp {amount}đ qua MBBank',
                created_at=datetime.now()
            )
            db.session.add(transaction)
            db.session.commit()
            
            logger.info(f"✅ ĐÃ TẠO GIAO DỊCH: {transaction_code} - {amount}đ")
        
        # Xóa loading
        await loading_msg.delete()
        
        # Push lên Render (chạy ngầm, không block)
        asyncio.create_task(push_user_to_render(user.id, username))
        asyncio.create_task(push_transaction_to_render(transaction_code, amount, user.id, username))
        
        # Tạo QR code
        content = f"NAP {transaction_code} tu {user.id}"  # ✅ ĐÚNG: NAP MÃGD tu USERID
        encoded_content = urllib.parse.quote(content)
        qr_url = f"https://img.vietqr.io/image/{MB_BIN}-{MB_ACCOUNT}-compact2.jpg?amount={amount}&addInfo={encoded_content}&accountName={MB_NAME}"

        # Tạo keyboard
        keyboard = [
            [InlineKeyboardButton("✅ TÔI ĐÃ CHUYỂN KHOẢN", callback_data=f"deposit_check_{transaction_code}")],
            [InlineKeyboardButton("💰 Nạp số khác", callback_data="menu_deposit")],
            [InlineKeyboardButton("📱 Thuê số", callback_data="menu_rent")],
            [InlineKeyboardButton("🔙 Menu chính", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Gửi ảnh QR với caption ĐÚNG FORMAT
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=qr_url,
            caption=f"""📌 **THÔNG TIN CHUYỂN KHOẢN**

🏦 **STK:** `{MB_ACCOUNT}`
👤 **Chủ TK:** {MB_NAME}
💰 **Số tiền:** {amount:,}đ
📝 **Nội dung:** `{content}`
🆔 **User ID của bạn:** `{user.id}`

👇 **Bấm nút 'TÔI ĐÃ CHUYỂN KHOẢN' sau khi chuyển!""",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Xóa message cũ
        try:
            await query.delete_message()
        except:
            pass
        
    except Exception as e:
        logger.error(f"Lỗi deposit_amount_callback: {e}")
        await safe_send_message(update, "❌ Có lỗi xảy ra! Vui lòng thử lại.")

async def deposit_check_callback(update: Update, context: Context):
    """Xử lý khi user bấm 'TÔI ĐÃ CHUYỂN KHOẢN' - FIX LỖI EDIT"""
    query = update.callback_query
    await safe_answer_callback(query, "📝 Đang ghi nhận...")
    
    try:
        transaction_code = query.data.split('_')[2]
        logger.info(f"💰 User báo đã chuyển khoản - Mã GD: {transaction_code}")
        
        # ===== FIX: KIỂM TRA TRƯỚC KHI EDIT =====
        try:
            await query.edit_message_text(
                text="⏳ **ĐANG XỬ LÝ...**\n\nVui lòng chờ trong giây lát.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Không thể edit message: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⏳ **ĐANG XỬ LÝ...**\n\nVui lòng chờ trong giây lát.",
                parse_mode='Markdown'
            )
        
        with app.app_context():
            transaction = Transaction.query.filter_by(
                transaction_code=transaction_code, 
                status='pending'
            ).first()
            
            if not transaction:
                await safe_send_message(
                    update,
                    f"❌ **KHÔNG TÌM THẤY GIAO DỊCH**\n\nMã GD: {transaction_code}\nVui lòng thử lại hoặc liên hệ admin."
                )
                return
            
            # Cập nhật thời gian
            transaction.updated_at = datetime.now()
            db.session.commit()
            
            # Lấy user để push lại
            user = User.query.get(transaction.user_id)
            if user:
                # Push lại (chạy ngầm)
                asyncio.create_task(push_user_to_render(user.user_id, user.username or f"user_{user.user_id}"))
                asyncio.create_task(push_transaction_to_render(
                    transaction_code, transaction.amount, user.user_id, user.username
                ))
        
        # Gửi thông báo chờ xử lý
        text = f"""⏳ **ĐANG XỬ LÝ GIAO DỊCH**

💰 **Số tiền:** {transaction.amount:,}đ
📝 **Mã GD:** `{transaction_code}`

✅ **Đã ghi nhận yêu cầu nạp tiền của bạn.**

🤖 **Hệ thống đang chờ xác nhận từ ngân hàng.**
⏰ **Tiền sẽ được cộng tự động sau 1-5 phút.**

⚠️ **KHÔNG CẦN BẤM NÚT NHIỀU LẦN**
📢 **Bạn sẽ nhận thông báo khi giao dịch hoàn tất.**"""
        
        keyboard = [[InlineKeyboardButton("🔙 Quay lại menu", callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send_message(update, text, reply_markup)
        
    except Exception as e:
        logger.error(f"Lỗi deposit_check_callback: {e}")
        await safe_send_message(update, "❌ **LỖI XỬ LÝ**\n\nVui lòng thử lại sau.")

async def check_deposit_status(update: Update, context: Context):
    """Lệnh kiểm tra trạng thái giao dịch thủ công - TỐI ƯU HÓA"""
    try:
        if not context.args:
            await safe_send_message(
                update,
                "❌ **CÚ PHÁP SAI**\n\nVui lòng nhập: `/check MÃ_GD`\nVí dụ: `/check MANUAL_20260307153425`"
            )
            return
        
        code = context.args[0].upper()
        
        # Gửi loading
        loading_msg = await update.message.reply_text("🔄 Đang kiểm tra...")
        
        # Kiểm tra trên Render
        try:
            response = requests.post(
                f"{RENDER_URL}/api/check-transaction",
                json={'code': code},
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                
                await loading_msg.delete()
                
                if data.get('exists'):
                    status_text = {
                        'pending': '⏳ Đang chờ xử lý',
                        'success': '✅ Đã thành công',
                        'failed': '❌ Thất bại'
                    }.get(data['status'], '❓ Không xác định')
                    
                    # Kiểm tra local
                    with app.app_context():
                        local_trans = Transaction.query.filter_by(transaction_code=code).first()
                        if local_trans:
                            user = User.query.get(local_trans.user_id)
                            local_status = local_trans.status
                            local_balance = user.balance if user else 0
                        else:
                            local_status = 'not_found'
                            local_balance = 0
                    
                    text = (
                        f"🔍 **KIỂM TRA GIAO DỊCH {code}**\n\n"
                        f"🌐 **Render:** {status_text}\n"
                        f"💻 **Local:** {local_status}\n"
                        f"💰 **Số tiền:** {data['amount']:,}đ\n"
                        f"🆔 **User ID:** {data['user_id']}\n"
                        f"💵 **Số dư hiện tại:** {local_balance:,}đ\n\n"
                        f"{'✅ Giao dịch đã thành công!' if data['status'] == 'success' else '⏳ Vui lòng chờ xử lý...'}"
                    )
                else:
                    text = f"❌ **KHÔNG TÌM THẤY**\n\nMã giao dịch `{code}` không tồn tại."
            else:
                await loading_msg.delete()
                text = f"⚠️ **LỖI KẾT NỐI**\n\nKhông thể kiểm tra trạng thái."
                
        except Exception as e:
            await loading_msg.delete()
            logger.error(f"Lỗi check status: {e}")
            text = f"⚠️ **LỖI**\n\nKhông thể kết nối đến server."
        
        keyboard = [[InlineKeyboardButton("🔙 Quay lại menu", callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send_message(update, text, reply_markup)
            
    except Exception as e:
        logger.error(f"Lỗi check_deposit_status: {e}")
        await safe_send_message(update, "⚠️ **LỖI XỬ LÝ**\n\nVui lòng thử lại sau.")