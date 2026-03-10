import asyncio
import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TimedOut, NetworkError

logger = logging.getLogger(__name__)

# ==================== DECORATOR RETRY ====================
def retry_on_timeout(max_retries=2, delay=1):
    """Tự động retry khi bị timeout"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (TimedOut, NetworkError) as e:
                    if attempt == max_retries - 1:
                        logger.error(f"❌ Thất bại sau {max_retries} lần: {e}")
                        raise
                    logger.warning(f"⏰ Timeout lần {attempt + 1}, thử lại sau {delay}s...")
                    await asyncio.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator

# ==================== HÀM GỬI TIN NHẮN TỐI ƯU ====================
async def safe_send_message(update: Update, text: str, reply_markup=None, parse_mode='Markdown'):
    """Gửi tin nhắn an toàn, không bị timeout"""
    try:
        # Thử gửi với timeout ngắn
        message = await update.effective_chat.send_message(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            read_timeout=5,
            write_timeout=5,
            connect_timeout=5,
            pool_timeout=5
        )
        return message
    except TimedOut:
        # Thử lại với timeout dài hơn
        logger.warning("⏰ Timeout lần 1, thử lại với timeout 10s...")
        try:
            message = await update.effective_chat.send_message(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                read_timeout=10,
                write_timeout=10,
                connect_timeout=10,
                pool_timeout=10
            )
            return message
        except TimedOut:
            # Lần cuối, gửi không có markup
            logger.warning("⏰ Timeout lần 2, gửi tin nhắn đơn giản...")
            return await update.effective_chat.send_message(
                text=text + "\n\n⚠️ Đang xử lý chậm, vui lòng đợi...",
                read_timeout=15
            )
    except Exception as e:
        logger.error(f"❌ Lỗi gửi tin nhắn: {e}")
        return None

async def safe_edit_message(query, text: str, reply_markup=None, parse_mode='Markdown'):
    """Sửa tin nhắn an toàn"""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except TimedOut:
        logger.warning("⏰ Timeout khi edit, thử lại...")
        await asyncio.sleep(1)
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        except:
            pass
    except Exception as e:
        logger.error(f"❌ Lỗi edit: {e}")

# ==================== TẠO MENU NHANH ====================
def create_menu_keyboard(buttons, row_width=2):
    """Tạo keyboard nhanh, tối ưu bộ nhớ"""
    keyboard = []
    row = []
    
    for i, (text, callback) in enumerate(buttons):
        row.append(InlineKeyboardButton(text, callback_data=callback))
        if len(row) == row_width:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)

# ==================== CACHE MENU ====================
menu_cache = {}
menu_cache_time = {}
CACHE_DURATION = 300  # 5 phút

def get_cached_menu(menu_name, create_func):
    """Lấy menu từ cache nếu còn hạn"""
    import time
    now = time.time()
    
    if menu_name in menu_cache and now - menu_cache_time.get(menu_name, 0) < CACHE_DURATION:
        return menu_cache[menu_name]
    
    menu = create_func()
    menu_cache[menu_name] = menu
    menu_cache_time[menu_name] = now
    return menu