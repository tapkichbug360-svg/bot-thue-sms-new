from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import ContextTypes  # Cập nhật import mới (v20+)
from database.models import User, db
from datetime import datetime
import logging
import requests
import os

logger = logging.getLogger(__name__)

RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-new.onrender.com')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem số dư tài khoản - ƯU TIÊN LOCAL, FALLBACK RENDER + TỐI ƯU MƯỢT"""
    user = update.effective_user
    user_id = user.id

    # === TRẢ LỜI NGAY LẬP TỨC ĐỂ USER THẤY PHẢN HỒI (giảm cảm giác lag) ===
    if update.callback_query:
        await update.callback_query.answer(text="Đang kiểm tra số dư...", show_alert=False, cache_time=0)
    else:
        # Nếu là lệnh /balance, gửi tin nhắn loading trước
        loading_msg = await update.message.reply_text("🔄 Đang tải số dư...")

    # === LUÔN LẤY TỪ LOCAL TRƯỚC (NHANH, ĐẢM BẢO HIỂN THỊ ĐÚNG) ===
    balance = 0
    username = user.first_name
    with app.app_context():
        db_user = User.query.filter_by(user_id=user_id).first()
        if db_user:
            balance = db_user.balance
            username = db_user.username or user.first_name
            logger.info(f"💰 Local balance: {balance}đ cho user {user_id}")
        else:
            logger.warning(f"⚠️ Không tìm thấy user {user_id} trong local DB")

    # === THỬ LẤY TỪ RENDER NGẦM (KHÔNG CHỜ, KHÔNG ẢNH HƯỞNG HIỂN THỊ BAN ĐẦU) ===
    render_balance = None
    try:
        response = requests.post(
            f"{RENDER_URL}/api/check-user",
            json={'user_id': user_id},
            timeout=4,  # Tăng nhẹ timeout nhưng vẫn nhanh
        )
        
        if response.status_code == 200:
            data = response.json()
            render_balance = data.get('balance', 0)
            logger.info(f"🌐 Render balance: {render_balance}đ")
            
            # Nếu render cao hơn → cập nhật local NGẦM (không chờ)
            if render_balance > balance:
                logger.info(f"🔄 Cập nhật local từ Render: {balance}đ → {render_balance}đ")
                with app.app_context():
                    db_user = User.query.filter_by(user_id=user_id).first()
                    if db_user:
                        db_user.balance = render_balance
                        db.session.commit()
                        balance = render_balance  # Cập nhật biến để hiển thị ngay
        else:
            logger.warning(f"Render API trả {response.status_code}")
    except (requests.Timeout, requests.ConnectionError, Exception) as e:
        logger.debug(f"Render không phản hồi kịp: {e} (không ảnh hưởng hiển thị)")

    # === XÂY DỰNG NỘI DUNG (SAU KHI ĐÃ CÓ DỮ LIỆU NHANH NHẤT) ===
    text = (
        f"💰 **SỐ DƯ TÀI KHOẢN**\n\n"
        f"• User ID: `{user_id}`\n"
        f"• Tên: {username}\n"
        f"• Username: @{user.username or 'Chưa có'}\n\n"
        f"💵 **Số dư hiện tại**: **{balance:,}đ**\n\n"
        f"🔽 Chọn thao tác tiếp theo:"
    )

    keyboard = [
        [InlineKeyboardButton("💳 Nạp tiền", callback_data="menu_deposit")],
        [InlineKeyboardButton("📱 Thuê số", callback_data="menu_rent")],
        [InlineKeyboardButton("🔙 Menu chính", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # === GỬI / CHỈNH SỬA TIN NHẮN (ƯU TIÊN NHANH, KHÔNG CHỜ) ===
    try:
        if update.callback_query:
            # Edit ngay tin nhắn cũ (mượt nhất)
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            # Xóa loading nếu có, rồi gửi mới
            if 'loading_msg' in locals():
                await loading_msg.delete()
            await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Lỗi khi gửi/edit menu số dư: {e}")
        # Fallback: gửi text đơn giản nếu edit fail
        fallback_text = f"💰 Số dư hiện tại: {balance:,}đ (lỗi hiển thị menu, thử lại nhé!)"
        if update.callback_query:
            await update.callback_query.edit_message_text(fallback_text)
        else:
            await update.message.reply_text(fallback_text)
