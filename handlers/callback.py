from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import CallbackContext as Context
from database.models import User, Rental
from datetime import datetime
import logging
import asyncio
import time

# Import các hàm từ các handlers khác
from handlers.balance import balance_command
from handlers.deposit import deposit_command, deposit_amount_callback, deposit_check_callback
from handlers.rent import (
    rent_command, rent_service_callback, rent_network_callback,
    rent_confirm_callback, rent_check_callback, rent_cancel_callback,
    rent_list_callback, rent_view_callback
)

logger = logging.getLogger(__name__)

# ==================== HÀM TIỆN ÍCH TỐI ƯU ====================
async def safe_answer_callback(query, text=None, show_alert=False):
    """Answer callback an toàn"""
    try:
        await query.answer(text=text, show_alert=show_alert, cache_time=0)
    except Exception as e:
        logger.debug(f"Answer callback error: {e}")

async def safe_edit_message(query, text, reply_markup=None, parse_mode=None, max_retries=2):
    """Sửa tin nhắn an toàn, tự động retry và fallback khi không có text"""
    for attempt in range(max_retries):
        try:
            # Kiểm tra xem message có text không
            if query.message.text is None:
                # Nếu không có text, gửi message mới
                await query.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
                # Xóa message cũ nếu có thể
                try:
                    await query.message.delete()
                except:
                    pass
                return True
            
            # Nếu có text, thử edit
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True
            
        except Exception as e:
            error_str = str(e).lower()
            if "no text in the message" in error_str or "message can't be edited" in error_str:
                # Lỗi do không có text hoặc không edit được - gửi message mới
                try:
                    # Gửi message mới
                    await query.message.reply_text(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                    # Xóa message cũ
                    try:
                        await query.message.delete()
                    except:
                        pass
                    return True
                except Exception as send_error:
                    logger.error(f"Send fallback failed: {send_error}")
                    return False
            elif attempt == max_retries - 1:
                logger.error(f"Edit message failed: {e}")
                # Thử gửi message mới nhưng không xóa cũ
                try:
                    await query.message.reply_text(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                    return True
                except:
                    return False
            await asyncio.sleep(0.5)
    return False

async def safe_send_message(context, chat_id, text, reply_markup=None, parse_mode=None):
    """Gửi tin nhắn mới an toàn"""
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception as e:
        logger.error(f"Send message failed: {e}")
        return False

async def safe_return_to_home(query, context, text="🎯 **MENU CHÍNH**\n\nChọn chức năng bên dưới:"):
    """Hàm chuyên dụng để quay về home an toàn"""
    try:
        # Kiểm tra loại message
        if query.message.text is None:
            # Message không phải text - gửi mới
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=text,
                reply_markup=main_menu,
                parse_mode='Markdown'
            )
            # Xóa message cũ
            try:
                await query.message.delete()
            except:
                pass
        else:
            # Message có text - thử edit
            await safe_edit_message(query, text, main_menu, 'Markdown')
    except Exception as e:
        logger.error(f"Safe return to home failed: {e}")
        # Fallback cuối cùng
        await safe_send_message(
            context, 
            query.message.chat.id, 
            text, 
            main_menu, 
            'Markdown'
        )

# ==================== CACHE MENU ====================
menu_cache = {}
menu_cache_time = {}
CACHE_DURATION = 300  # 5 phút

def get_cached_menu(menu_name, create_func):
    """Lấy menu từ cache"""
    now = time.time()
    if menu_name in menu_cache and now - menu_cache_time.get(menu_name, 0) < CACHE_DURATION:
        return menu_cache[menu_name]
    
    menu = create_func()
    menu_cache[menu_name] = menu
    menu_cache_time[menu_name] = now
    return menu

def create_main_menu():
    """Tạo menu chính"""
    keyboard = [
        [InlineKeyboardButton("📱 Thuê số", callback_data='menu_rent'),
         InlineKeyboardButton("📋 Số đang thuê", callback_data='menu_rent_list')],
        [InlineKeyboardButton("💰 Số dư", callback_data='menu_balance'),
         InlineKeyboardButton("💳 Nạp tiền", callback_data='menu_deposit')],
        [InlineKeyboardButton("📜 Lịch sử", callback_data='menu_history'),
         InlineKeyboardButton("👤 Tài khoản", callback_data='menu_profile')],
        [InlineKeyboardButton("❓ Hướng dẫn", callback_data='menu_help')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_back_menu(back_to="menu_main"):
    """Tạo menu chỉ có nút quay lại"""
    keyboard = [[InlineKeyboardButton("🔙 Quay lại", callback_data=back_to)]]
    return InlineKeyboardMarkup(keyboard)

# Cache menu chính
main_menu = get_cached_menu("main", create_main_menu)

# ==================== MENU CALLBACK CHÍNH ====================
async def menu_callback(update: Update, context: Context):
    """Xử lý tất cả các callback từ menu - ĐÃ TỐI ƯU VÀ SỬA LỖI"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    data = query.data
    
    # ===== MENU CHÍNH =====
    if data == 'menu_main':
        text = "🎯 **MENU CHÍNH**\n\nChọn chức năng bên dưới:"
        await safe_return_to_home(query, context, text)
    
    # ===== CÁC MENU CHUYỂN HƯỚNG =====
    elif data == 'menu_balance':
        await balance_command(update, context)
    
    elif data == 'menu_deposit':
        await deposit_command(update, context)
    
    elif data.startswith('deposit_amount_'):
        await deposit_amount_callback(update, context)
    
    elif data.startswith('deposit_check_'):
        await deposit_check_callback(update, context)
    
    elif data == 'menu_rent':
        await rent_command(update, context)
    
    elif data == 'menu_rent_list':
        await rent_list_callback(update, context)
    
    elif data.startswith('rent_service_'):
        await rent_service_callback(update, context)
    
    elif data.startswith('rent_network_'):
        await rent_network_callback(update, context)
    
    elif data.startswith('rent_confirm_'):
        await rent_confirm_callback(update, context)
    
    elif data.startswith('rent_check_'):
        await rent_check_callback(update, context)
    
    elif data.startswith('rent_cancel_'):
        await rent_cancel_callback(update, context)
    
    elif data.startswith('rent_view_'):
        await rent_view_callback(update, context)
    
    # ===== LỊCH SỬ =====
    elif data == 'menu_history':
        user = update.effective_user
        with app.app_context():
            rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).limit(10).all()
        
        if not rentals:
            text = "📜 **LỊCH SỬ GIAO DỊCH**\n\n*Chưa có giao dịch nào.*"
        else:
            text = "📜 **LỊCH SỬ GIAO DỊCH**\n\n"
            for r in rentals:
                status_icon = {
                    'waiting': '⏳',
                    'success': '✅',
                    'cancelled': '❌',
                    'expired': '⏰'
                }.get(r.status, '❓')
                text += f"{status_icon} **{r.created_at.strftime('%H:%M %d/%m')}** - {r.service_name}\n"
                if r.phone_number:
                    text += f"   📞 `{r.phone_number}`\n"
                if r.otp_code and r.status == 'success':
                    text += f"   🔑 OTP: `{r.otp_code}`\n"
                text += "\n"
        
        reply_markup = create_back_menu("menu_main")
        
        # Kiểm tra loại message trước khi edit
        if query.message.text is None:
            # Message không phải text
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            try:
                await query.message.delete()
            except:
                pass
        else:
            await safe_edit_message(query, text, reply_markup, 'Markdown')
    
    # ===== HƯỚNG DẪN =====
    elif data == 'menu_help':
        text = """❓ **HƯỚNG DẪN SỬ DỤNG**

1️⃣ **Nạp tiền:**
   • Chọn 'Nạp tiền' → Chọn số tiền
   • Chuyển khoản đến số tài khoản:
     `666666291005` - NGUYEN THE LAM
   • Nhập nội dung chính xác để được cộng tự động

2️⃣ **Thuê số:**
   • Chọn 'Thuê số' → Chọn dịch vụ
   • Chọn nhà mạng → Xác nhận
   • Bot tự động kiểm tra OTP trong 5 phút

3️⃣ **Quản lý số:**
   • 'Số đang thuê': Xem tất cả số đang active
   • Click vào số để xem chi tiết/hủy số

⚠️ **TUÂN THỦ PHÁP LUẬT:**
• Nghiêm cấm lừa đảo, cá độ, đánh bạc
• Không tạo bank ảo, tiền ảo
• Vi phạm sẽ khóa tài khoản vĩnh viễn

📞 **Hỗ trợ:** @makkllai"""
        
        reply_markup = create_back_menu("menu_main")
        
        # Kiểm tra loại message trước khi edit
        if query.message.text is None:
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            try:
                await query.message.delete()
            except:
                pass
        else:
            await safe_edit_message(query, text, reply_markup, 'Markdown')
    
    # ===== THÔNG TIN TÀI KHOẢN =====
    elif data == 'menu_profile':
        user = update.effective_user
        with app.app_context():
            db_user = User.query.filter_by(user_id=user.id).first()
            balance = db_user.balance if db_user else 0
            total_rentals = db_user.total_rentals if db_user else 0
            total_spent = db_user.total_spent if db_user else 0
            created_at = db_user.created_at if db_user else datetime.now()
        
        text = f"""👤 **THÔNG TIN TÀI KHOẢN**

• **User ID:** `{user.id}`
• **Tên:** {user.first_name}
• **Username:** @{user.username or 'N/A'}
• **Ngày tham gia:** {created_at.strftime('%d/%m/%Y')}

📊 **THỐNG KÊ:**
• **Số dư:** `{balance:,}đ`
• **Đã thuê:** {total_rentals} số
• **Đã chi:** `{total_spent:,}đ`"""
        
        reply_markup = create_back_menu("menu_main")
        
        # Kiểm tra loại message trước khi edit
        if query.message.text is None:
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            try:
                await query.message.delete()
            except:
                pass
        else:
            await safe_edit_message(query, text, reply_markup, 'Markdown')