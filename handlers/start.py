from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext as Context
from database.models import User, Rental, db
from datetime import datetime
import logging
import os
import requests
import asyncio
# Đầu file, thêm imports
from datetime import datetime, timedelta, timezone

# Thêm sau imports
VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

logger = logging.getLogger(__name__)

MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-v2.onrender.com')

async def sync_balance_with_render(user_id):
    """Đồng bộ số dư với Render - CHỈ LẤY SỐ CAO HƠN"""
    try:
        # Gọi API lấy số dư từ Render
        response = requests.post(
            f"{RENDER_URL}/api/get-user-balance",
            json={'user_id': user_id},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            render_balance = data.get('balance')
            
            if render_balance is not None:
                with app.app_context():
                    user = User.query.filter_by(user_id=user_id).first()
                    if user:
                        old_balance = user.balance
                        
                        # ==== QUAN TRỌNG: CHỈ CẬP NHẬT KHI RENDER CAO HƠN ====
                        if render_balance > user.balance:
                            logger.info(f"💰 Render cao hơn: {render_balance}đ > {user.balance}đ -> Cập nhật")
                            user.balance = render_balance
                            
                            # Cập nhật các giao dịch
                            if 'transactions' in data:
                                from database.models import DepositTransaction
                                for trans_data in data['transactions']:
                                    transaction = DepositTransaction.query.filter_by(
                                        transaction_id=trans_data['code']
                                    ).first()
                                    if transaction and transaction.status != 'completed':
                                        transaction.status = trans_data['status']
                                        transaction.processed_at = datetime.now()
                            
                            db.session.commit()
                            logger.info(f"✅ Đồng bộ user {user_id}: {old_balance}đ → {render_balance}đ")
                            return True
                            
                        elif render_balance < user.balance:
                            # Render thấp hơn -> push local lên Render
                            logger.info(f"⚠️ Render thấp hơn: {render_balance}đ < {user.balance}đ -> Push local")
                            asyncio.create_task(push_user_balance_to_render(
                                user_id, 
                                user.balance, 
                                user.username or f"user_{user_id}"
                            ))
                        else:
                            logger.info(f"✅ Số dư đồng bộ: {user.balance}đ")
                    else:
                        logger.warning(f"⚠️ Không tìm thấy user {user_id} trong database")
            else:
                logger.warning(f"⚠️ Render trả về balance = null cho user {user_id}")
        else:
            logger.warning(f"⚠️ Render API trả về {response.status_code}")
            
    except requests.exceptions.Timeout:
        logger.warning(f"⏰ Timeout khi lấy balance từ Render cho user {user_id}")
    except requests.exceptions.ConnectionError:
        logger.warning(f"🔌 Lỗi kết nối Render cho user {user_id}")
    except Exception as e:
        logger.error(f"❌ Lỗi đồng bộ balance user {user_id}: {e}")
    
    return False

async def push_user_balance_to_render(user_id, balance, username):
    """Push số dư local lên Render"""
    try:
        response = requests.post(
            f"{RENDER_URL}/api/update-balance",
            json={
                'user_id': user_id,
                'balance': balance,
                'username': username
            },
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Đã push balance {balance}đ cho user {user_id} lên Render")
            return True
        else:
            logger.warning(f"⚠️ Push balance thất bại: {response.status_code}")
            
    except requests.exceptions.Timeout:
        logger.warning(f"⏰ Timeout push balance user {user_id}")
    except Exception as e:
        logger.error(f"❌ Lỗi push balance user {user_id}: {e}")
    
    return False

async def push_user_to_render(user_id, username):
    """Đẩy user mới lên Render"""
    try:
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id, 'username': username},
            timeout=10
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

async def start_command(update: Update, context: Context):
    """Xử lý lệnh /start"""
    user = update.effective_user
    username = user.username or user.first_name or f"user_{user.id}"
    
    with app.app_context():
        existing_user = User.query.filter_by(user_id=user.id).first()
        
        if not existing_user:
            new_user = User(
                user_id=user.id,
                username=username,
                balance=0,
                created_at=datetime.now(),
                last_active=datetime.now()
            )
            db.session.add(new_user)
            db.session.commit()
            logger.info(f"🆕 Người dùng mới: {user.id} - {user.first_name}")
            
            # Push user mới lên Render
            asyncio.create_task(push_user_to_render(user.id, username))
            
            current_balance = 0
        else:
            # Lưu số dư cũ
            old_balance = existing_user.balance
            logger.info(f"👤 Người dùng cũ: {user.id} - {user.first_name} - Số dư local: {old_balance}đ")
            
            # Cập nhật thời gian hoạt động và username
            existing_user.last_active = datetime.now()
            existing_user.username = username
            db.session.commit()
            
            # Đồng bộ số dư với Render (chỉ lấy số cao hơn)
            await sync_balance_with_render(user.id)
            
            # Lấy lại số dư sau khi đồng bộ
            db.session.refresh(existing_user)
            current_balance = existing_user.balance
            
            if old_balance != current_balance:
                logger.info(f"💰 Đồng bộ user {user.id}: {old_balance}đ → {current_balance}đ")
    
    # Tạo keyboard menu chính
    keyboard = [
        [InlineKeyboardButton("📱 Thuê số", callback_data='menu_rent'),
         InlineKeyboardButton("📋 Số đang thuê", callback_data='menu_rent_list')],
        [InlineKeyboardButton("💰 Số dư", callback_data='menu_balance'),
         InlineKeyboardButton("💳 Nạp tiền", callback_data='menu_deposit')],
        [InlineKeyboardButton("📜 Lịch sử", callback_data='menu_history'),
         InlineKeyboardButton("👤 Tài khoản", callback_data='menu_profile')],
        [InlineKeyboardButton("❓ Hướng dẫn", callback_data='menu_help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_msg = (
        f"🎉 **Chào mừng {user.first_name} đến với Bot Thuê SMS!**\n\n"
        f"💰 **Số dư hiện tại:** {current_balance:,}đ\n\n"
        f"🤖 Bot cung cấp dịch vụ thuê số điện thoại ảo:\n"
        f"• Facebook • Google • Tiktok • Shopee • Các dịch vụ khác\n\n"
        f"⚠️ **TUÂN THỦ PHÁP LUẬT:**\n"
        f"• Nghiêm cấm lừa đảo, cá độ, bank ảo\n"
        f"• Vi phạm sẽ khóa tài khoản\n\n"
        f"🏦 **MBBANK**\n"
        f"🔢 **Số TK:** `{MB_ACCOUNT}`\n"
        f"👤 **Chủ TK:** `{MB_NAME}`\n\n"
        f"📌 **Hướng dẫn nhanh:**\n"
        f"• Chọn 'Thuê số' để bắt đầu\n"
        f"• Chọn 'Số đang thuê' để xem các số đã thuê"
    )
    
    await update.message.reply_text(
        welcome_msg, 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )

async def menu_command(update: Update, context: Context):
    """Hiển thị menu chính"""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Đồng bộ số dư trước khi hiển thị menu
    user = update.effective_user
    await sync_balance_with_render(user.id)
    
    keyboard = [
        [InlineKeyboardButton("📱 Thuê số", callback_data='menu_rent'),
         InlineKeyboardButton("📋 Số đang thuê", callback_data='menu_rent_list')],
        [InlineKeyboardButton("💰 Số dư", callback_data='menu_balance'),
         InlineKeyboardButton("💳 Nạp tiền", callback_data='menu_deposit')],
        [InlineKeyboardButton("📜 Lịch sử", callback_data='menu_history'),
         InlineKeyboardButton("👤 Tài khoản", callback_data='menu_profile')],
        [InlineKeyboardButton("❓ Hướng dẫn", callback_data='menu_help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🎯 **MENU CHÍNH**\n\nChọn chức năng bạn muốn sử dụng:"
    
    if query:
        try:
            await query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Lỗi edit message: {e}")
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

async def cancel(update: Update, context: Context):
    """Hủy thao tác hiện tại"""
    query = update.callback_query
    keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI MENU", callback_data="menu_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "❌ **ĐÃ HỦY THAO TÁC!**\n\nBạn có thể chọn chức năng khác."
    
    if query:
        await query.answer()
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def help_command(update: Update, context: Context):
    """Hiển thị hướng dẫn chi tiết"""
    text = (
        "📚 **HƯỚNG DẪN CHI TIẾT**\n\n"
        "1️⃣ **Nạp tiền:**\n"
        "   • Chọn 'Nạp tiền' → Chọn số tiền\n"
        "   • Chuyển khoản đến tài khoản:\n"
        f"     🏦 {MB_ACCOUNT} - {MB_NAME}\n"
        "   • Nhập nội dung chính xác để được cộng tự động\n\n"
        "2️⃣ **Thuê số:**\n"
        "   • Chọn 'Thuê số' → Chọn dịch vụ\n"
        "   • Chọn nhà mạng → Xác nhận\n"
        "   • Bot tự động kiểm tra OTP trong 5 phút\n\n"
        "3️⃣ **Quản lý số:**\n"
        "   • 'Số đang thuê': Xem tất cả số đang active\n"
        "   • Click vào số để xem chi tiết/hủy số\n"
        "   • Hủy số được hoàn tiền (nếu chưa có OTP)\n\n"
        "4️⃣ **Kiểm tra giao dịch:**\n"
        "   • Dùng lệnh `/check MÃ_GD` để xem trạng thái\n"
        "   • Ví dụ: `/check MANUAL_20260307153425`\n\n"
        "⚠️ **QUY ĐỊNH:**\n"
        "• Không lừa đảo, cá độ, đánh bạc\n"
        "• Không tạo bank ảo, tiền ảo\n"
        "• Vi phạm sẽ khóa tài khoản vĩnh viễn\n\n"
        f"📞 **Hỗ trợ:** Liên hệ admin @makkllai"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Quay lại menu", callback_data="menu_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )

async def check_command(update: Update, context: Context):
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
                timeout=10
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
                        from database.models import DepositTransaction, User
                        local_trans = DepositTransaction.query.filter_by(
                            transaction_id=code
                        ).first()
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
                        f"🆔 **User ID:** {data['user_id']}\n"
                        f"💵 **Số dư hiện tại:** {local_balance:,}đ\n\n"
                        f"{'✅ Giao dịch đã thành công!' if data['status'] == 'success' else '⏳ Vui lòng chờ xử lý...'}",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        f"❌ **KHÔNG TÌM THẤY**\n\nMã giao dịch `{code}` không tồn tại.",
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text(
                    f"⚠️ **LỖI KẾT NỐI**\n\nKhông thể kiểm tra trạng thái.",
                    parse_mode='Markdown'
                )
        except requests.exceptions.ConnectionError:
            await update.message.reply_text(
                "⚠️ **LỖI KẾT NỐI**\n\nKhông thể kết nối đến server Render.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Lỗi check status: {e}")
            await update.message.reply_text(
                f"⚠️ **LỖI**\n\nKhông thể kiểm tra trạng thái.",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Lỗi check_deposit_status: {e}")
        await update.message.reply_text(
            "⚠️ **LỖI XỬ LÝ**\n\nVui lòng thử lại sau.",
            parse_mode='Markdown'
        )

async def balance_command(update: Update, context: Context):
    """Xem số dư tài khoản - CÓ ĐỒNG BỘ VỚI RENDER"""
    user = update.effective_user
    
    # Đồng bộ số dư từ Render trước
    await sync_balance_with_render(user.id)
    
    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).first()
        
        if not db_user:
            text = "❌ KHÔNG TÌM THẤY TÀI KHOẢN\n\nVui lòng gửi /start để đăng ký."
            if update.callback_query:
                await update.callback_query.edit_message_text(text)
            else:
                await update.message.reply_text(text)
            return
        
        balance = db_user.balance
        total_spent = db_user.total_spent
        total_rentals = db_user.total_rentals
        
        text = (
            f"💰 **SỐ DƯ TÀI KHOẢN**\n\n"
            f"• **User ID:** `{user.id}`\n"
            f"• **Tên:** {user.first_name}\n"
            f"• **Username:** @{user.username or 'N/A'}\n\n"
            f"💵 **Số dư hiện tại:** `{balance:,}đ`\n"
            f"📊 **Đã thuê:** {total_rentals} số\n"
            f"💸 **Tổng chi:** {total_spent:,}đ\n\n"
            f"🔽 **Chọn thao tác:**"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 Nạp tiền", callback_data="menu_deposit")],
            [InlineKeyboardButton("📱 Thuê số", callback_data="menu_rent")],
            [InlineKeyboardButton("🔙 Menu chính", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )

async def history_command(update: Update, context: Context):
    """Xem lịch sử giao dịch"""
    user = update.effective_user
    
    with app.app_context():
        # Lấy lịch sử thuê số
        rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).limit(10).all()
        
        if not rentals:
            keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI MENU", callback_data="menu_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "📭 **Bạn chưa có giao dịch nào**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        text = "📜 **LỊCH SỬ GIAO DỊCH**\n\n"
        for r in rentals:
            status_icon = {
                'waiting': '⏳',
                'success': '✅',
                'cancelled': '❌',
                'expired': '⏰'
            }.get(r.status, '❓')
            
            text += f"{status_icon} {r.created_at.strftime('%d/%m %H:%M')} - {r.service_name}\n"
            text += f"   📞 `{r.phone_number}` - {r.price_charged:,}đ\n"
            if r.otp_code and r.status == 'success':
                text += f"   🔑 OTP: `{r.otp_code}`\n"
            text += "\n"
        
        keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI MENU", callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def cancel_command(update: Update, context: Context):
    """Hủy thao tác hiện tại"""
    # Xóa user_data
    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI MENU", callback_data="menu_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "❌ **ĐÃ HỦY THAO TÁC**\n\nBạn có thể bắt đầu lại từ menu.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Import app từ bot - để cuối file tránh circular import
from bot import app 