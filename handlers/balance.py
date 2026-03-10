from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import CallbackContext as Context
from database.models import User, db
from datetime import datetime
import logging
import requests
import os
import asyncio

logger = logging.getLogger(__name__)

RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-new.onrender.com')

# Cache để tránh gọi API liên tục
balance_cache = {}
balance_cache_time = {}
CACHE_DURATION = 5  # Cache 5 giây thôi để luôn mới

async def get_user_balance_fast(user_id):
    """Lấy balance siêu nhanh - từ cache hoặc local"""
    import time
    now = time.time()
    
    # Kiểm tra cache trước
    if user_id in balance_cache and now - balance_cache_time.get(user_id, 0) < CACHE_DURATION:
        return balance_cache[user_id]
    
    # Nếu không có cache, lấy từ local
    with app.app_context():
        db_user = User.query.filter_by(user_id=user_id).first()
        if db_user:
            balance = db_user.balance
            # Cache lại
            balance_cache[user_id] = balance
            balance_cache_time[user_id] = now
            return balance
    
    return 0

async def update_balance_cache(user_id, new_balance):
    """Cập nhật cache balance"""
    import time
    balance_cache[user_id] = new_balance
    balance_cache_time[user_id] = time.time()

async def sync_balance_from_render(user_id):
    """Đồng bộ balance từ Render - ƯU TIÊN LẤY TỪ RENDER"""
    try:
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            render_balance = data.get('balance', 0)
            
            with app.app_context():
                user = User.query.filter_by(user_id=user_id).first()
                if user:
                    if user.balance != render_balance:
                        old_balance = user.balance
                        user.balance = render_balance
                        db.session.commit()
                        logger.info(f"🔄 Đồng bộ user {user_id}: {old_balance}đ → {render_balance}đ")
                        await update_balance_cache(user_id, render_balance)
                    return render_balance
                else:
                    # Tạo user mới nếu chưa có
                    new_user = User(
                        user_id=user_id,
                        username=f"user_{user_id}",
                        balance=render_balance,
                        created_at=datetime.now(),
                        last_active=datetime.now()
                    )
                    db.session.add(new_user)
                    db.session.commit()
                    logger.info(f"🆕 Tạo user mới từ Render: {user_id}")
                    await update_balance_cache(user_id, render_balance)
                    return render_balance
        else:
            logger.warning(f"⚠️ Render API trả về {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Lỗi sync từ Render: {e}")
    
    return None

async def balance_command(update: Update, context: Context):
    """Xem số dư tài khoản - LUÔN LẤY TỪ RENDER TRƯỚC"""
    user = update.effective_user
    user_id = user.id
    
    # Phản hồi ngay để chống lag
    if update.callback_query:
        await update.callback_query.answer(text="🔄 Đang kiểm tra...", show_alert=False, cache_time=0)
        message = update.callback_query.message
        is_callback = True
    else:
        message = await update.message.reply_text("🔄 Đang kiểm tra số dư...")
        is_callback = False
    
    # ƯU TIÊN LẤY TỪ RENDER
    render_balance = await sync_balance_from_render(user_id)
    
    if render_balance is not None:
        balance = render_balance
        source = "🌐 Render"
    else:
        # Fallback về local nếu Render lỗi
        balance = await get_user_balance_fast(user_id)
        source = "💻 Local"
    
    # Lấy thông tin user
    with app.app_context():
        db_user = User.query.filter_by(user_id=user_id).first()
        username = db_user.username if db_user else user.first_name
        total_rentals = db_user.total_rentals if db_user else 0
        total_spent = db_user.total_spent if db_user else 0
    
    # Tạo text hiển thị
    text = (
        f"💰 **SỐ DƯ TÀI KHOẢN**\n\n"
        f"• **User ID:** `{user_id}`\n"
        f"• **Tên:** {username}\n"
        f"• **Username:** @{user.username or 'Chưa có'}\n\n"
        f"💵 **Số dư hiện tại:** `{balance:,}đ`\n"
        f"📊 **Đã thuê:** {total_rentals} số\n"
        f"💸 **Tổng chi:** {total_spent:,}đ\n\n"
        f"🔄 *Nguồn: {source}*\n\n"
        f"🔽 **Chọn thao tác:**"
    )
    
    # Tạo keyboard
    keyboard = [
        [
            InlineKeyboardButton("💳 NẠP TIỀN", callback_data="menu_deposit"),
            InlineKeyboardButton("📱 THUÊ SỐ", callback_data="menu_rent")
        ],
        [
            InlineKeyboardButton("🔄 ĐỒNG BỘ", callback_data="sync_balance"),
            InlineKeyboardButton("📋 LỊCH SỬ", callback_data="menu_history")
        ],
        [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Gửi response
    try:
        if is_callback:
            await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Lỗi gửi message: {e}")
        # Fallback
        if is_callback:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    
    # Cập nhật cache
    await update_balance_cache(user_id, balance)

async def sync_balance_callback(update: Update, context: Context):
    """Xử lý callback đồng bộ thủ công"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    await query.answer(text="🔄 Đang đồng bộ...", show_alert=False)
    
    # Hiển thị trạng thái
    await query.edit_message_text(
        text="🔄 **ĐANG ĐỒNG BỘ SỐ DƯ...**\n\nVui lòng chờ trong giây lát.",
        parse_mode="Markdown"
    )
    
    # Đồng bộ từ Render
    render_balance = await sync_balance_from_render(user_id)
    
    if render_balance is not None:
        text = (
            f"✅ **ĐỒNG BỘ THÀNH CÔNG!**\n\n"
            f"💰 **Số dư hiện tại:** `{render_balance:,}đ`"
        )
    else:
        # Lấy từ local
        balance = await get_user_balance_fast(user_id)
        text = (
            f"ℹ️ **KHÔNG THỂ ĐỒNG BỘ TỪ RENDER**\n\n"
            f"💰 **Số dư hiện tại:** `{balance:,}đ`\n"
            f"⚠️ Dùng số dư local."
        )
    
    # Tạo keyboard
    keyboard = [
        [InlineKeyboardButton("💰 XEM LẠI SỐ DƯ", callback_data="menu_balance")],
        [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )