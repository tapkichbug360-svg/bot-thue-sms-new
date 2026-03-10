from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import ContextTypes
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
CACHE_DURATION = 30  # Cache 30 giây

async def get_user_balance_fast(user_id):
    """Lấy balance siêu nhanh - từ cache hoặc local"""
    # Kiểm tra cache trước
    import time
    now = time.time()
    
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

async def sync_balance_from_render(user_id, current_local_balance):
    """Đồng bộ từ Render (chạy ngầm, không block) - ĐÃ FIX CACHE"""
    try:
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id},
            timeout=3
        )
        
        if response.status_code == 200:
            data = response.json()
            render_balance = data.get('balance', 0)
            
            if render_balance > current_local_balance:
                logger.info(f"🔄 Render cao hơn: {render_balance} > {current_local_balance}")
                
                with app.app_context():
                    db_user = User.query.filter_by(user_id=user_id).first()
                    if db_user:
                        db_user.balance = render_balance
                        db.session.commit()
                        # ✅ CẬP NHẬT CACHE
                        await update_balance_cache(user_id, render_balance)
                        return render_balance, True
                        
            elif render_balance < current_local_balance:
                logger.info(f"📤 Local cao hơn: push {current_local_balance}đ lên Render")
                # Push lên Render (chạy ngầm)
                asyncio.create_task(push_balance_to_render(user_id, current_local_balance))
                
                # ✅ QUAN TRỌNG: CẬP NHẬT CACHE VỚI GIÁ TRỊ LOCAL
                await update_balance_cache(user_id, current_local_balance)
                
                # Có thể thông báo cho user nếu muốn
                # asyncio.create_task(notify_balance_synced(user_id, current_local_balance))
                
            # else: render_balance == current_local_balance, không làm gì
                
    except Exception as e:
        logger.debug(f"Render sync error: {e}")
    
    return current_local_balance, False
async def notify_balance_synced(user_id, balance):
    """Gửi thông báo nhẹ khi đồng bộ xong"""
    try:
        from telegram import Bot
        bot = Bot(token=os.getenv('BOT_TOKEN'))
        
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ **Đồng bộ thành công!**\n💰 Số dư: `{balance:,}đ`",
            parse_mode="Markdown"
        )
    except:
        pass

async def push_balance_to_render(user_id, balance):
    """Push balance lên Render (chạy ngầm)"""
    try:
        requests.post(
            f"{RENDER_URL}/api/update-balance",
            json={'user_id': user_id, 'balance': balance},
            timeout=2
        )
    except:
        pass

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem số dư tài khoản - SIÊU MƯỢT, KHÔNG LAG"""
    user = update.effective_user
    user_id = user.id
    
    # === BƯỚC 1: PHẢN HỒI NGAY LẬP TỨC (CHỐNG LAG) ===
    start_time = datetime.now()
    
    if update.callback_query:
        # Nếu là callback từ menu, answer ngay
        await update.callback_query.answer(
            text="🔄 Đang kiểm tra...", 
            show_alert=False, 
            cache_time=0
        )
        message = update.callback_query.message
        is_callback = True
    else:
        # Nếu là lệnh /balance, gửi loading message
        message = await update.message.reply_text("🔄 Đang tải số dư...")
        is_callback = False
    
    # === BƯỚC 2: LẤY BALANCE SIÊU NHANH (CACHE / LOCAL) ===
    balance = await get_user_balance_fast(user_id)
    
    # Lấy thông tin user
    with app.app_context():
        db_user = User.query.filter_by(user_id=user_id).first()
        if db_user:
            username = db_user.username or user.first_name
            total_spent = db_user.total_spent or 0
            total_rentals = db_user.total_rentals or 0
        else:
            # Tạo user mới nếu chưa có
            new_user = User(
                user_id=user_id,
                username=user.first_name,
                balance=0,
                created_at=datetime.now(),
                last_active=datetime.now()
            )
            db.session.add(new_user)
            db.session.commit()
            username = user.first_name
            total_spent = 0
            total_rentals = 0
            balance = 0
    
    # === BƯỚC 3: GỬI RESPONSE NGAY (HIỂN THỊ BALANCE TỨC THỜI) ===
    text = (
        f"💰 **SỐ DƯ TÀI KHOẢN**\n\n"
        f"• **User ID:** `{user_id}`\n"
        f"• **Tên:** {username}\n"
        f"• **Username:** @{user.username or 'Chưa có'}\n\n"
        f"💵 **Số dư hiện tại:** `{balance:,}đ`\n"
        f"📊 **Đã thuê:** {total_rentals} số\n"
        f"💸 **Tổng chi:** {total_spent:,}đ\n\n"
        f"⏱️ *Phản hồi trong {(datetime.now() - start_time).microseconds // 1000}ms*\n\n"
        f"🔽 **Chọn thao tác:**"
    )
    
    # Tạo keyboard đẹp hơn
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
            await message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Lỗi gửi message: {e}")
        # Fallback: gửi message mới
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
    
    # === BƯỚC 4: ĐỒNG BỘ NGẦM VỚI RENDER (KHÔNG BLOCK) ===
    asyncio.create_task(sync_balance_from_render(user_id, balance))


# === CALLBACK XỬ LÝ ĐỒNG BỘ THỦ CÔNG ===
async def sync_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý callback đồng bộ thủ công"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    await query.answer(text="🔄 Đang đồng bộ...", show_alert=False)
    
    # Hiển thị trạng thái đang đồng bộ
    await query.edit_message_text(
        text="🔄 **ĐANG ĐỒNG BỘ SỐ DƯ...**\n\nVui lòng chờ trong giây lát.",
        parse_mode="Markdown"
    )
    
    # Lấy balance hiện tại
    current_balance = await get_user_balance_fast(user_id)
    
    # Đồng bộ với Render
    new_balance, updated = await sync_balance_from_render(user_id, current_balance)
    
    if updated:
        text = (
            f"✅ **ĐỒNG BỘ THÀNH CÔNG!**\n\n"
            f"💰 **Số dư mới:** `{new_balance:,}đ`\n"
            f"📈 **Tăng:** `+{new_balance - current_balance:,}đ`"
        )
    else:
        text = (
            f"ℹ️ **KHÔNG CÓ THAY ĐỔI**\n\n"
            f"💰 **Số dư hiện tại:** `{current_balance:,}đ`"
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


# === HÀM XÓA CACHE (CHO ADMIN) ===
async def clear_balance_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xóa cache balance (chỉ admin)"""
    user_id = update.effective_user.id
    
    # Kiểm tra admin (thêm user_id admin của bạn)
    ADMIN_IDS = [5180190297]  # Thay bằng ID admin thật
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Bạn không có quyền thực hiện lệnh này!")
        return
    
    global balance_cache, balance_cache_time
    balance_cache.clear()
    balance_cache_time.clear()
    
    await update.message.reply_text("✅ Đã xóa cache balance!")