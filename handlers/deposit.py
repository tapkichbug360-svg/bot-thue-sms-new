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

logger = logging.getLogger(__name__)

MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
MB_BIN = os.getenv('MB_BIN', '970422')
RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-v2.onrender.com')

# Cache để tránh push trùng
pushed_transactions = set()

async def push_user_to_render(user_id, username):
    """Đẩy user lên Render ngay lập tức"""
    try:
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id, 'username': username},
            timeout=5
        )
        if response.status_code == 200:
            logger.info(f"✅ Đã push user {user_id} lên Render thành công")
            return True
        else:
            logger.warning(f"⚠️ Push user {user_id} thất bại: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Lỗi push user {user_id}: {e}")
        return False

async def push_transaction_to_render(transaction_code, amount, user_id, username):
    """Đẩy giao dịch lên Render ngay sau khi tạo"""
    global pushed_transactions
    
    # Tránh push trùng
    if transaction_code in pushed_transactions:
        logger.info(f"ℹ️ Giao dịch {transaction_code} đã được push trước đó")
        return True
    
    try:
        response = requests.post(
            f"{RENDER_URL}/api/sync-pending",
            json={
                'transactions': [{
                    'code': transaction_code,
                    'amount': amount,
                    'user_id': user_id,
                    'username': username
                }]
            },
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Đã đẩy giao dịch {transaction_code} lên Render thành công: {result}")
            pushed_transactions.add(transaction_code)
            
            # Giới hạn kích thước cache
            if len(pushed_transactions) > 100:
                pushed_transactions.clear()
            
            return True
        else:
            logger.warning(f"⚠️ Đẩy giao dịch {transaction_code} thất bại: {response.status_code}")
            try:
                error_detail = response.json()
                logger.error(f"📝 Chi tiết lỗi: {error_detail}")
            except:
                pass
            return False
    except requests.exceptions.Timeout:
        logger.error(f"⏰ Timeout khi đẩy giao dịch {transaction_code}")
        return False
    except Exception as e:
        logger.error(f"❌ Lỗi đẩy giao dịch {transaction_code}: {e}")
        return False

async def deposit_command(update: Update, context: Context):
    """Hiển thị menu nạp tiền"""
    transaction_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    context.user_data['pending_deposit'] = {'code': transaction_code, 'amount': None}
    
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

📝 **Nội dung:** NAP {transaction_code}

💰 **Chọn số tiền:**"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

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
            
            logger.info(f"✅ ĐÃ TẠO GIAO DỊCH: {transaction_code} - {amount}đ cho user {user.id}")
        
        # === TỰ ĐỘNG ĐẨY LÊN RENDER NGAY LẬP TỨC ===
        await asyncio.gather(
            push_user_to_render(user.id, username),
            push_transaction_to_render(transaction_code, amount, user.id, username)
        )
        
        # Tạo QR code
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

👇 **Bấm nút 'TÔI ĐÃ CHUYỂN KHOẢN' sau khi chuyển!""",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        await query.delete_message()
        
    except Exception as e:
        logger.error(f"Lỗi deposit_amount_callback: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="❌ Có lỗi xảy ra! Vui lòng thử lại."
        )

async def deposit_check_callback(update: Update, context: Context):
    """Xử lý khi user bấm 'TÔI ĐÃ CHUYỂN KHOẢN'"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    
    try:
        transaction_code = query.data.split('_')[2]
        logger.info(f"💰 User báo đã chuyển khoản - Mã GD: {transaction_code}")
        
        with app.app_context():
            transaction = Transaction.query.filter_by(
                transaction_code=transaction_code, 
                status='pending'
            ).first()
            
            if not transaction:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ **KHÔNG TÌM THẤY GIAO DỊCH**\n\nMã GD: {transaction_code}\nVui lòng thử lại hoặc liên hệ admin.",
                    parse_mode='Markdown'
                )
                return
            
            # Cập nhật thời gian
            transaction.updated_at = datetime.now()
            db.session.commit()
            
            # Lấy user để push lại (phòng trường hợp)
            user = User.query.get(transaction.user_id)
            if user:
                # Push lại user và transaction để đảm bảo
                await asyncio.gather(
                    push_user_to_render(user.user_id, user.username or f"user_{user.user_id}"),
                    push_transaction_to_render(transaction_code, transaction.amount, user.user_id, user.username)
                )
            
            # GỬI THÔNG BÁO CHỜ XỬ LÝ
            text = f"""⏳ **ĐANG XỬ LÝ GIAO DỊCH**

💰 **Số tiền:** {transaction.amount:,}đ
📝 **Mã GD:** `{transaction_code}`

✅ **Đã ghi nhận yêu cầu nạp tiền của bạn.**

🤖 **Hệ thống đang chờ xác nhận từ ngân hàng.**
⏰ **Tiền sẽ được cộng tự động sau 1-5 phút.**

⚠️ **KHÔNG CẦN BẤM NÚT NHIỀU LẦN**
📢 **Bạn sẽ nhận thông báo khi giao dịch hoàn tất.**"""
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Lỗi deposit_check_callback: {e}")
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
                "❌ **CÚ PHÁP SAI**\n\nVui lòng nhập: `/check MÃ_GD`\nVí dụ: `/check MANUAL_20260307153425`",
                parse_mode='Markdown'
            )
            return
        
        code = context.args[0].upper()
        
        # Kiểm tra trên Render
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
                        'pending': '⏳ Đang chờ xử lý',
                        'success': '✅ Đã thành công',
                        'failed': '❌ Thất bại'
                    }.get(data['status'], '❓ Không xác định')
                    
                    # Kiểm tra thêm trên local để xác nhận
                    with app.app_context():
                        local_trans = Transaction.query.filter_by(transaction_code=code).first()
                        if local_trans:
                            user = User.query.get(local_trans.user_id)
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
                        f"🆔 **User ID:** {data['user_id']}\n"
                        f"💵 **Số dư hiện tại:** {local_balance:,}đ\n\n"
                        f"{'✅ Giao dịch đã thành công!' if data['status'] == 'success' else '⏳ Vui lòng chờ xử lý...'}",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        f"❌ **KHÔNG TÌM THẤY**\n\nMã giao dịch `{code}` không tồn tại trong hệ thống.",
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text(
                    f"⚠️ **LỖI KẾT NỐI**\n\nKhông thể kiểm tra trạng thái. Vui lòng thử lại sau.",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Lỗi check status: {e}")
            await update.message.reply_text(
                f"⚠️ **LỖI**\n\nKhông thể kết nối đến server.",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Lỗi check_deposit_status: {e}")
        await update.message.reply_text(
            "⚠️ **LỖI XỬ LÝ**\n\nVui lòng thử lại sau.",
            parse_mode='Markdown'
        )

# Hàm tiện ích để fix user nếu cần
def fix_user_manual(user_id, username, amount, transaction_code):
    """Fix user thủ công (dùng khi cần)"""
    try:
        # Push lên Render
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id, 'username': username},
            timeout=5
        )
        print(f"Push user: {response.json()}")
        
        # Push transaction
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
        print(f"Push transaction: {response.json()}")
        
        # Cập nhật local
        with app.app_context():
            user = User.query.filter_by(user_id=user_id).first()
            if not user:
                user = User(
                    user_id=user_id,
                    username=username,
                    balance=0,
                    created_at=datetime.now()
                )
                db.session.add(user)
                db.session.flush()
            
            user.balance += amount
            
            transaction = Transaction(
                user_id=user.id,
                amount=amount,
                type='deposit',
                status='success',
                transaction_code=transaction_code,
                description=f"Manual fix",
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.session.add(transaction)
            db.session.commit()
            
            print(f"✅ Đã fix user {user_id} - {username} +{amount}đ")
            return True
    except Exception as e:
        print(f"❌ Lỗi fix: {e}")
        return False