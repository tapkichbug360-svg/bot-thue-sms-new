from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import CallbackContext as Context
from database.models import User, Rental, BalanceLog, db
from datetime import datetime, timedelta, timezone
import requests
import os
import logging
import time
import asyncio
from typing import Dict
import aiohttp

VN_TZ = timezone(timedelta(hours=7))

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

logger = logging.getLogger(__name__)

API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL')

services_cache = []
services_cache_time = 0
services_lock = asyncio.Lock()

networks_cache = []
networks_cache_time = 0
networks_lock = asyncio.Lock()

auto_check_tasks: Dict[int, asyncio.Task] = {}
rental_locks: Dict[int, asyncio.Lock] = {}  # <--- THÊM: lock riêng cho từng rental

# ==================== HÀM TIỆN ÍCH ====================

async def safe_answer_callback(query, text=None, show_alert=False):
    try:
        await query.answer(text=text, show_alert=show_alert, cache_time=0)
    except Exception as e:
        logger.debug(f"Answer callback error: {e}")

async def safe_edit_message(query, text, reply_markup=None, parse_mode='Markdown', max_retries=2):
    for attempt in range(max_retries):
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Edit message failed: {e}")
                return False
            await asyncio.sleep(0.5)
    return False

async def safe_send_message(context, chat_id, text, reply_markup=None, parse_mode='Markdown'):
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

async def safe_delete_message(message):
    try:
        if message:
            await message.delete()
    except Exception as e:
        logger.debug(f"Delete message failed: {e}")

# ==================== CACHE ====================

def get_cached_services():
    global services_cache, services_cache_time
    if services_cache and time.time() - services_cache_time < 300:
        return services_cache
    return None

def get_cached_networks():
    global networks_cache, networks_cache_time
    if networks_cache and time.time() - networks_cache_time < 300:
        return networks_cache
    return None

# ==================== LOCK & SAFE REFUND ====================

async def get_rental_lock(rental_id: int) -> asyncio.Lock:
    if rental_id not in rental_locks:
        rental_locks[rental_id] = asyncio.Lock()
    return rental_locks[rental_id]

async def safe_refund_rental(bot, rental_id: int, chat_id: int, phone: str, reason: str = "timeout"):
    """Hoàn tiền an toàn - dùng chung cho timeout và cancel"""
    lock = await get_rental_lock(rental_id)
    async with lock:
        with app.app_context():
            rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
            if not rental or rental.refunded:
                return False

            user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()
            if not user:
                return False

            refund = rental.price_charged
            old_balance = user.balance
            user.balance += refund
            rental.status = 'expired' if reason == "timeout" else 'cancelled'
            rental.refunded = True
            rental.refund_amount = refund
            rental.refunded_at = get_vn_time()

            try:
                db.session.commit()
                logger.info(f"SAFE REFUND {reason.upper()} | rental {rental_id} | +{refund}đ | old: {old_balance} → new: {user.balance}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"{'⏰' if reason == 'timeout' else '✅'} **{'HẾT HẠN' if reason == 'timeout' else 'HỦY'} THÀNH CÔNG!**\n\n"
                         f"📞 `{phone}`\n"
                         f"💰 **Hoàn lại:** {refund:,}đ\n"
                         f"💵 **Số dư mới:** {user.balance:,}đ",
                    parse_mode='Markdown'
                )
                return True
            except Exception as e:
                db.session.rollback()
                logger.error(f"Refund failed {rental_id}: {e}")
                return False

# ==================== CORE ====================

async def delete_previous_menu(update: Update, context: Context):
    try:
        if update and update.callback_query and update.callback_query.message:
            await safe_delete_message(update.callback_query.message)
        elif update and update.message:
            await safe_delete_message(update.message)
    except Exception as e:
        logger.error(f"Lỗi xóa menu cũ: {e}")

# ==================== API ====================

async def get_services():
    async with services_lock:
        global services_cache, services_cache_time
        cached = get_cached_services()
        if cached:
            return cached
        try:
            url = f"{BASE_URL}/service/get_service_by_api_key?api_key={API_KEY}"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"API services HTTP lỗi: {response.status}")
                        return []
                    data = await response.json()
            if isinstance(data, dict) and data.get('status') == 200:
                services_cache = data.get('data', [])
                services_cache_time = time.time()
                return services_cache
            else:
                logger.error(f"Lỗi API services: {data}")
                return []
        except Exception as e:
            logger.error(f"Lỗi kết nối API services: {e}")
            return []

async def get_networks():
    async with networks_lock:
        global networks_cache, networks_cache_time
        cached = get_cached_networks()
        if cached:
            return cached
        try:
            url = f"{BASE_URL}/network/get-network-by-api-key?api_key={API_KEY}"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"API networks HTTP lỗi: {response.status}")
                        return []
                    data = await response.json()
            if isinstance(data, dict) and data.get('status') == 200:
                networks_cache = data.get('data', [])
                networks_cache_time = time.time()
                return networks_cache
            else:
                logger.error(f"Lỗi API networks: {data}")
                return []
        except Exception as e:
            logger.error(f"Lỗi kết nối API networks: {e}")
            return []

async def get_account_info():
    try:
        url = f"{BASE_URL}/yourself/information-by-api-key?api_key={API_KEY}"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
        if isinstance(data, dict) and data.get('status') == 200:
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Lỗi lấy thông tin tài khoản: {e}")
        return None

# ==================== COMMAND ====================

async def rent_command(update: Update, context: Context):
    logger.info("📱 rent_command được gọi")

    if update.callback_query:
        await safe_answer_callback(update.callback_query, "📱 Đang tải...")

    await delete_previous_menu(update, context)

    user = update.effective_user

    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).first()
        if db_user and db_user.is_banned:
            text = "❌ **TÀI KHOẢN CỦA BẠN ĐÃ BỊ KHÓA**\n\nVui lòng liên hệ admin để biết thêm chi tiết."
            await safe_send_message(context, update.effective_chat.id, text)
            return

    loading_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ **ĐANG TẢI DANH SÁCH DỊCH VỤ...**\n\nVui lòng chờ trong giây lát.",
        parse_mode='Markdown'
    )

    services = await get_services()

    if not services:
        await loading_msg.edit_text(
            "❌ **KHÔNG THỂ LẤY DANH SÁCH DỊCH VỤ**\n\n"
            "• Kiểm tra kết nối API\n"
            "• Thử lại sau vài phút\n"
            "• Liên hệ admin nếu lỗi tiếp diễn",
            parse_mode='Markdown'
        )
        return

    banned_services = ['ZALO', 'TELEGRAM', 'BANK', 'TIENAO', 'CRYPTO']
    filtered_services = []
    for sv in services:
        try:
            name_upper = sv['name'].upper()
        except:
            continue
        is_banned = any(banned in name_upper for banned in banned_services)
        if not is_banned:
            filtered_services.append(sv)

    if not filtered_services:
        await loading_msg.edit_text(
            "⚠️ **KHÔNG CÓ DỊCH VỤ NÀO KHẢ DỤNG**\n\n"
            "Tất cả dịch vụ hiện đang tạm ngưng.",
            parse_mode='Markdown'
        )
        return

    keyboard = []
    row = []
    for i, sv in enumerate(filtered_services):
        try:
            original_price = int(float(sv.get('price', 1200)))
            final_price = original_price + 1000
        except:
            original_price = 1200
            final_price = 2200

        button = InlineKeyboardButton(
            f"{sv.get('name','Unknown')} - {final_price:,}đ",
            callback_data=f"rent_service_{sv.get('id','0')}_{sv.get('name','Unknown')}_{original_price}"
        )
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("📋 DANH SÁCH SỐ CỦA TÔI", callback_data="menu_rent_list")])
    keyboard.append([InlineKeyboardButton("🔙 QUAY LẠI MENU", callback_data="menu_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"📱 **THUÊ SỐ NHẬN OTP**\n\n"
        f"📊 **Tổng số dịch vụ:** {len(filtered_services)}\n\n"
        f"⚠️ **TUÂN THỦ PHÁP LUẬT:**\n"
        f"• Nghiêm cấm đánh bạc, cá độ, lừa đảo\n"
        f"• Nghiêm cấm tạo bank ảo, tiền ảo\n"
        f"• Dịch vụ ZALO, Telegram hiện đang CẤM!\n"
        f"• Mọi vi phạm sẽ khóa tài khoản vĩnh viễn\n\n"
        f"👇 **Chọn dịch vụ bên dưới:**"
    )

    await loading_msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# (các hàm rent_service_callback, rent_network_callback giữ nguyên như code cũ của bạn)

async def rent_confirm_callback(update: Update, context: Context):
    query = update.callback_query
    await safe_answer_callback(query, "⏳ Đang xử lý...")

    try:
        data = query.data.split('_', 4)
        service_id = data[2]
        final_price = int(data[3])
        network_id = data[4]
    except Exception as e:
        logger.error(f"Lỗi parse confirm: {e}")
        await safe_edit_message(query, "❌ **LỖI DỮ LIỆU**\n\nVui lòng chọn lại.")
        return

    if not API_KEY or not BASE_URL:
        await safe_edit_message(query, "❌ **LỖI CẤU HÌNH**\n\nVui lòng liên hệ admin.")
        return

    user = update.effective_user

    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).with_for_update().first()

        if not db_user:
            await safe_edit_message(query, "❌ **KHÔNG TÌM THẤY TÀI KHOẢN**\n\nVui lòng gửi /start.")
            return

        # Giới hạn số lượng waiting để chống spam
        active_waiting = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status == 'waiting',
            Rental.refunded == False
        ).count()
        if active_waiting >= 8:
            await safe_edit_message(query,
                "⚠️ **BẠN ĐANG CÓ QUÁ NHIỀU SỐ CHỜ OTP** (tối đa 8)\n\n"
                "Vui lòng hủy bớt số cũ trước khi thuê thêm!")
            return

        recent = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.created_at > datetime.now() - timedelta(seconds=10)
        ).count()
        if recent > 3:
            await safe_edit_message(query,
                "⚠️ **THUÊ QUÁ NHANH**\n\nVui lòng chờ 10 giây giữa các lần thuê.")
            return

        if db_user.balance < final_price:
            shortage = final_price - db_user.balance
            keyboard = [
                [InlineKeyboardButton("💳 NẠP TIỀN NGAY", callback_data="menu_deposit")],
                [InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]
            ]
            await safe_edit_message(query,
                f"❌ **SỐ DƯ KHÔNG ĐỦ!**\n\nCần: {final_price:,}đ | Có: {db_user.balance:,}đ | Thiếu: {shortage:,}đ",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return

    await safe_delete_message(query.message)

    loading_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ **ĐANG XỬ LÝ YÊU CẦU...**\n\n🤖 Vui lòng chờ trong giây lát.",
        parse_mode='Markdown'
    )

    try:
        url = f"{BASE_URL}/sim/get_sim"
        params = {'api_key': API_KEY, 'service_id': service_id}
        if network_id and network_id != 'None':
            params['network_id'] = network_id

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status == 401:
                    await loading_msg.edit_text("❌ **LỖI XÁC THỰC API**\n\nVui lòng liên hệ admin.")
                    return
                response_data = await response.json()

        if response_data.get('status') == 200:
            sim_data = response_data.get('data', {})
            phone = sim_data.get('phone')
            otp_id = sim_data.get('otpId')
            sim_id = sim_data.get('simId')
            actual_price = sim_data.get('payment', final_price - 1000)

            with app.app_context():
                existing = Rental.query.filter(
                    Rental.phone_number == phone,
                    Rental.status.in_(['waiting', 'completed'])
                ).first()
                if existing:
                    await loading_msg.edit_text("❌ **SỐ NÀY ĐÃ ĐƯỢC CẤP**\n\nVui lòng thử lại sau.")
                    return

                db.session.refresh(db_user)
                if db_user.balance < final_price:
                    await loading_msg.edit_text("❌ **SỐ DƯ KHÔNG ĐỦ** (đã thay đổi)")
                    return

                rent_info = context.user_data.get('rent', {})
                if not rent_info:
                    await loading_msg.edit_text("❌ **LỖI SESSION**\n\nChọn lại từ đầu.")
                    return

                rental = Rental(
                    user_id=user.id,
                    service_id=int(service_id),
                    service_name=rent_info['service_name'],
                    phone_number=phone,
                    otp_id=otp_id,
                    sim_id=sim_id,
                    cost=actual_price,
                    price_charged=final_price,
                    status='waiting',
                    created_at=get_vn_time(),
                    expires_at=get_vn_time() + timedelta(minutes=5)
                )
                db.session.add(rental)

                db_user.balance -= final_price
                db_user.total_spent += final_price
                db_user.total_rentals += 1
                db_user.updated_at = get_vn_time()

                db.session.commit()
                db.session.refresh(db_user)

                if 'rent' in context.user_data:
                    del context.user_data['rent']

                keyboard = [
                    [InlineKeyboardButton(f"📞 {phone} - {rent_info['service_name']}", callback_data=f"rent_view_{rental.id}")],
                    [InlineKeyboardButton("📋 DANH SÁCH SỐ", callback_data="menu_rent_list")],
                    [InlineKeyboardButton("🆕 THUÊ SỐ KHÁC", callback_data="menu_rent")],
                    [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
                ]

                await loading_msg.edit_text(
                    f"✅ **THUÊ SỐ THÀNH CÔNG!**\n\n"
                    f"📞 **Số:** `{phone}`\n"
                    f"📱 **Dịch vụ:** {rent_info['service_name']}\n"
                    f"💰 **Đã thanh toán:** {final_price:,}đ\n"
                    f"💵 **Số dư còn lại:** {db_user.balance:,}đ",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

                task = asyncio.create_task(
                    auto_check_otp_task(
                        context.bot,
                        update.effective_chat.id,
                        otp_id,
                        rental.id,
                        user.id,
                        rent_info['service_name'],
                        phone
                    )
                )
                auto_check_tasks[rental.id] = task

        else:
            error_msg = response_data.get('message', 'Không rõ lỗi')
            await loading_msg.edit_text(
                f"❌ **LỖI TỪ SERVER**\n\n{error_msg}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]]),
                parse_mode='Markdown'
            )

    except asyncio.TimeoutError:
        await loading_msg.edit_text("⏰ **TIMEOUT API**\n\nThử lại sau.")
    except Exception as e:
        logger.error(f"Lỗi thuê số: {e}")
        await loading_msg.edit_text("❌ **LỖI KẾT NỐI**\n\nThử lại sau.")

async def auto_check_otp_task(bot, chat_id: int, otp_id: str, rental_id: int, user_id: int, service_name: str, phone: str):
    logger.info(f"🤖 Auto-check OTP started for rental {rental_id}")

    max_checks = 150
    check_count = 0

    try:
        while check_count < max_checks:
            check_count += 1

            lock = await get_rental_lock(rental_id)
            async with lock:
                with app.app_context():
                    rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                    if not rental or rental.status != 'waiting' or rental.refunded:
                        return

                    if get_vn_time() > rental.expires_at:
                        await safe_refund_rental(bot, rental_id, chat_id, phone, "timeout")
                        return

            try:
                timeout = aiohttp.ClientTimeout(total=6)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        f"{BASE_URL}/otp/get_otp_by_phone_api_key",
                        params={'api_key': API_KEY, 'otp_id': otp_id}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('status') == 200:
                                otp_data = data.get('data', {})
                                otp_code = otp_data.get('code')
                                content = otp_data.get('content', '')
                                audio_url = otp_data.get('audio')

                                lock = await get_rental_lock(rental_id)
                                async with lock:
                                    with app.app_context():
                                        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                                        if rental and rental.status == 'waiting' and not rental.refunded:
                                            rental.status = "completed"
                                            rental.otp_code = otp_code or "Audio OTP"
                                            rental.content = content
                                            rental.updated_at = get_vn_time()
                                            db.session.commit()

                                if otp_code:
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=f"🔑 **MÃ OTP:** `{otp_code}`\n📝 {content}\n📱 **{service_name}**\n📞 `{phone}`",
                                        parse_mode='Markdown'
                                    )

                                if audio_url:
                                    try:
                                        await bot.send_message(chat_id=chat_id, text="⏳ Đang tải audio OTP...")
                                        async with aiohttp.ClientSession(timeout=30) as ses:
                                            async with ses.get(audio_url, headers={'User-Agent': 'Mozilla/5.0'}) as audio_resp:
                                                if audio_resp.status == 200:
                                                    audio_bytes = await audio_resp.read()
                                                    await bot.send_audio(
                                                        chat_id=chat_id,
                                                        audio=audio_bytes,
                                                        filename=f"otp_{rental_id}.mp3",
                                                        caption=f"📱 {service_name} | 📞 {phone}",
                                                        parse_mode='Markdown'
                                                    )
                                                else:
                                                    await bot.send_message(
                                                        chat_id=chat_id,
                                                        text=f"🔊 **AUDIO OTP:** [Nghe tại đây]({audio_url})",
                                                        parse_mode='Markdown'
                                                    )
                                    except Exception as e:
                                        logger.error(f"Audio error: {e}")
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=f"🔊 **AUDIO OTP:** [Nghe tại đây]({audio_url})",
                                            parse_mode='Markdown'
                                        )

                                if rental_id in auto_check_tasks:
                                    del auto_check_tasks[rental_id]
                                return

            except Exception as e:
                logger.debug(f"Check OTP error {rental_id}: {e}")

            await asyncio.sleep(5)

        # Hết thời gian mà chưa có OTP
        await safe_refund_rental(bot, rental_id, chat_id, phone, "timeout")

    except asyncio.CancelledError:
        logger.info(f"Auto-check {rental_id} cancelled")
    finally:
        auto_check_tasks.pop(rental_id, None)
        rental_locks.pop(rental_id, None)

async def rent_cancel_callback(update: Update, context: Context):
    query = update.callback_query
    await safe_answer_callback(query, "⏳ Đang hủy...")

    try:
        sim_id = query.data.split('_')[2]
        rental_id = int(query.data.split('_')[3])
    except:
        await query.edit_message_text("❌ Lỗi dữ liệu")
        return

    # Hủy task nếu đang chạy
    if rental_id in auto_check_tasks:
        try:
            auto_check_tasks[rental_id].cancel()
            await asyncio.sleep(0.4)
        except:
            pass
        auto_check_tasks.pop(rental_id, None)

    # Gọi API cancel (không bắt buộc thành công mới hoàn tiền)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/sim/cancel_api_key/{sim_id}?api_key={API_KEY}", timeout=8) as resp:
                pass  # chỉ gọi, không phụ thuộc kết quả
    except:
        pass

    # Hoàn tiền an toàn
    success = await safe_refund_rental(
        context.bot,
        rental_id,
        update.effective_chat.id,
        "",  # phone sẽ lấy trong hàm nếu cần
        "cancel"
    )

    if not success:
        await query.edit_message_text("❌ Số này đã được xử lý trước đó hoặc không thể hủy.")
        return

    keyboard = [
        [InlineKeyboardButton("🆕 THUÊ TIẾP", callback_data="menu_rent")],
        [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
    ]

    await query.edit_message_text(
        "✅ **ĐÃ HỦY SỐ THÀNH CÔNG!**\n\n"
        "💰 Tiền đã được hoàn lại đầy đủ vào số dư.\n"
        "Kiểm tra số dư trong menu Balance.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def rent_check_callback(update: Update, context: Context):
    """Kiểm tra OTP thủ công - GỬI CẢ TEXT VÀ AUDIO"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_', 3)
        otp_id = data[2]
        rental_id = int(data[3])
    except Exception as e:
        logger.error(f"Lỗi parse check: {e}")
        await query.edit_message_text("❌ **LỖI DỮ LIỆU**\n\nVui lòng thử lại.")
        return
    
    await query.edit_message_text(
        "⏳ **ĐANG KIỂM TRA OTP...**\n\nVui lòng chờ trong giây lát.",
        parse_mode='Markdown'
    )
    
    try:
        url = f"{BASE_URL}/otp/get_otp_by_phone_api_key"
        params = {'api_key': API_KEY, 'otp_id': otp_id}
        
        logger.info(f"🔍 Kiểm tra OTP cho otp_id={otp_id}")
        
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                try:
                    response_data = await response.json()
                except:
                    logger.error("API OTP trả JSON lỗi")
                    await query.edit_message_text("❌ **LỖI API**")
                    return
        
        logger.info(f"API check OTP response: {response_data}")
        
        with app.app_context():
            lock = await get_rental_lock(rental_id)
            async with lock:
                rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                
                if not rental:
                    await query.edit_message_text(
                        "❌ **KHÔNG TÌM THẤY THÔNG TIN THUÊ SỐ**\n\n"
                        "Vui lòng thử lại hoặc liên hệ admin.",
                        parse_mode='Markdown'
                    )
                    return
                
                if rental.refunded or rental.status != 'waiting':
                    await query.edit_message_text("⚠️ **SỐ NÀY ĐÃ ĐƯỢC XỬ LÝ** (hết hạn/hủy/hoàn tiền)")
                    return
                
                status = response_data.get('status')
                
                if status == 200:
                    otp_data = response_data.get('data', {})
                    otp_code = otp_data.get('code')
                    content = otp_data.get('content', '')
                    audio_url = otp_data.get('audio')
                    
                    rental.status = "completed"
                    rental.otp_code = otp_code or "Audio OTP"
                    rental.content = content
                    rental.updated_at = get_vn_time()
                    db.session.commit()
                    
                    if otp_code:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"✅ **MÃ OTP:** `{otp_code}`\n📝 {content}",
                            parse_mode='Markdown'
                        )
                    
                    if audio_url:
                        try:
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text="⏳ **ĐANG TẢI FILE AUDIO OTP...**",
                                parse_mode='Markdown'
                            )
                            
                            timeout = aiohttp.ClientTimeout(total=30)
                            async with aiohttp.ClientSession(timeout=timeout) as ses:
                                async with ses.get(audio_url, headers={'User-Agent': 'Mozilla/5.0'}) as audio_response:
                                    if audio_response.status == 200:
                                        audio_bytes = await audio_response.read()
                                        await context.bot.send_audio(
                                            chat_id=update.effective_chat.id,
                                            audio=audio_bytes,
                                            filename=f"otp_audio_{rental_id}.mp3",
                                            title=f"OTP Audio - {rental.service_name}",
                                            caption=f"📱 **{rental.service_name}**\n📞 `{rental.phone_number}`",
                                            parse_mode='Markdown'
                                        )
                                    else:
                                        await context.bot.send_message(
                                            chat_id=update.effective_chat.id,
                                            text=f"🔊 **LINK AUDIO OTP**\n\n📱 **{rental.service_name}**\n📞 `{rental.phone_number}`\n\n[Nhấn vào đây để nghe]({audio_url})",
                                            parse_mode='Markdown'
                                        )
                        except Exception as e:
                            logger.error(f"Lỗi tải audio: {e}")
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=f"🔊 **LINK AUDIO OTP**\n\n📱 **{rental.service_name}**\n📞 `{rental.phone_number}`\n\n[Nhấn vào đây để nghe]({audio_url})",
                                parse_mode='Markdown'
                            )
                    
                    elif not otp_code and not audio_url:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"✅ **ĐÃ NHẬN OTP**\n\n📱 **Dịch vụ:** {rental.service_name}\n📞 **Số:** `{rental.phone_number}`",
                            parse_mode='Markdown'
                        )
                    
                    await query.delete_message()
                
                elif status == 202:
                    expires_in = int((rental.expires_at - get_vn_time()).total_seconds() / 60)
                    await query.edit_message_text(
                        f"⏳ **CHƯA CÓ OTP**\n\n• Còn {max(0, expires_in)} phút",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("⏳ **ĐANG CHỜ OTP...**")
                    
    except asyncio.TimeoutError:
        await query.edit_message_text("❌ **TIMEOUT API**")
    except Exception as e:
        logger.error(f"Lỗi kiểm tra OTP: {e}")
        await query.edit_message_text("❌ **LỖI KẾT NỐI**")


async def auto_check_otp_task(bot, chat_id: int, otp_id: str, rental_id: int, user_id: int, service_name: str, phone: str):
    logger.info(f"🤖 Auto-check OTP started for rental {rental_id}")
    
    max_checks = 150
    check_count = 0
    
    try:
        while check_count < max_checks:
            check_count += 1
            
            lock = await get_rental_lock(rental_id)
            async with lock:
                with app.app_context():
                    rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                    if not rental or rental.status != 'waiting' or rental.refunded:
                        return
                    
                    if get_vn_time() > rental.expires_at:
                        await safe_refund_rental(bot, rental_id, chat_id, phone, "timeout")
                        return
            
            try:
                timeout = aiohttp.ClientTimeout(total=6)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        f"{BASE_URL}/otp/get_otp_by_phone_api_key",
                        params={'api_key': API_KEY, 'otp_id': otp_id}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('status') == 200:
                                otp_data = data.get('data', {})
                                otp_code = otp_data.get('code')
                                content = otp_data.get('content', '')
                                audio_url = otp_data.get('audio')
                                
                                lock = await get_rental_lock(rental_id)
                                async with lock:
                                    with app.app_context():
                                        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                                        if rental and rental.status == 'waiting' and not rental.refunded:
                                            rental.status = "completed"
                                            rental.otp_code = otp_code or "Audio OTP"
                                            rental.content = content
                                            rental.updated_at = get_vn_time()
                                            db.session.commit()
                                
                                if otp_code:
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=f"🔑 **MÃ OTP:** `{otp_code}`\n📝 {content}\n📱 **{service_name}**\n📞 `{phone}`",
                                        parse_mode='Markdown'
                                    )
                                
                                if audio_url:
                                    try:
                                        await bot.send_message(chat_id=chat_id, text="⏳ Đang tải audio OTP...")
                                        async with aiohttp.ClientSession(timeout=30) as ses:
                                            async with ses.get(audio_url, headers={'User-Agent': 'Mozilla/5.0'}) as audio_resp:
                                                if audio_resp.status == 200:
                                                    audio_bytes = await audio_resp.read()
                                                    await bot.send_audio(
                                                        chat_id=chat_id,
                                                        audio=audio_bytes,
                                                        filename=f"otp_{rental_id}.mp3",
                                                        caption=f"📱 {service_name} | 📞 {phone}",
                                                        parse_mode='Markdown'
                                                    )
                                                else:
                                                    await bot.send_message(
                                                        chat_id=chat_id,
                                                        text=f"🔊 **AUDIO OTP:** [Nghe tại đây]({audio_url})",
                                                        parse_mode='Markdown'
                                                    )
                                    except Exception as e:
                                        logger.error(f"Audio error: {e}")
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=f"🔊 **AUDIO OTP:** [Nghe tại đây]({audio_url})",
                                            parse_mode='Markdown'
                                        )
                                
                                auto_check_tasks.pop(rental_id, None)
                                return
                                
            except Exception as e:
                logger.debug(f"Check OTP error {rental_id}: {e}")
            
            await asyncio.sleep(5)
        
        # Timeout
        await safe_refund_rental(bot, rental_id, chat_id, phone, "timeout")
    
    except asyncio.CancelledError:
        logger.info(f"Auto-check {rental_id} cancelled")
    finally:
        auto_check_tasks.pop(rental_id, None)
        rental_locks.pop(rental_id, None)


async def rent_view_callback(update: Update, context: Context):
    """Xem chi tiết số đã thuê"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        rental_id = int(query.data.split('_')[2])
    except Exception:
        await query.edit_message_text("❌ Lỗi dữ liệu")
        return
    
    with app.app_context():
        rental = Rental.query.get(rental_id)
        
        if not rental:
            await query.edit_message_text(
                "❌ **KHÔNG TÌM THẤY THÔNG TIN THUÊ SỐ**\n\n"
                "Có thể số đã bị xóa hoặc không tồn tại.",
                parse_mode='Markdown'
            )
            return
        
        try:
            expires_in = int((rental.expires_at - get_vn_time()).total_seconds() / 60)
        except Exception:
            expires_in = 0

        if expires_in < 0:
            expires_in = 0
            
        status_text = {
            'waiting': f'⏳ Đang chờ OTP (còn {expires_in} phút)',
            'completed': '✅ Đã nhận OTP',
            'cancelled': '❌ Đã hủy',
            'expired': '⏰ Đã hết hạn'
        }.get(rental.status, 'Không xác định')
        
        text = f"""📱 **CHI TIẾT SỐ THUÊ**

• **Số:** `{rental.phone_number}`
• **Dịch vụ:** {rental.service_name}
• **Giá thuê:** {rental.price_charged:,}đ
• **Trạng thái:** {status_text}
• **Thời gian thuê:** {rental.created_at.strftime('%H:%M:%S %d/%m/%Y')}
"""
        
        keyboard = []

        if rental.status == 'waiting':
            if rental.otp_id:
                keyboard.append([
                    InlineKeyboardButton(
                        "🔍 KIỂM TRA OTP",
                        callback_data=f"rent_check_{rental.otp_id}_{rental.id}"
                    )
                ])
            if rental.sim_id:
                keyboard.append([
                    InlineKeyboardButton(
                        "❌ HỦY SỐ",
                        callback_data=f"rent_cancel_{rental.sim_id}_{rental.id}"
                    )
                ])

        elif rental.status == 'completed':
            keyboard.append([
                InlineKeyboardButton(
                    "🔄 THUÊ LẠI SỐ NÀY",
                    callback_data=f"rent_reuse_{rental.phone_number}_{rental.service_id}"
                )
            ])
        
        if rental.otp_code:
            text += f"🔑 **MÃ OTP:** `{rental.otp_code}`\n"
            if rental.content:
                text += f"📝 **Nội dung:** {rental.content}\n"
        
        keyboard.append([
            InlineKeyboardButton("📋 DANH SÁCH SỐ", callback_data="menu_rent_list")
        ])
        keyboard.append([
            InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )


async def rent_reuse_callback(update: Update, context: Context):
    """Thuê lại số đã từng thuê thành công"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_')
        phone = data[2]
        service_id = data[3]
    except Exception as e:
        logger.error(f"Lỗi parse reuse: {e}")
        await query.edit_message_text("❌ **LỖI DỮ LIỆU**\n\nVui lòng thử lại.")
        return
    
    user = update.effective_user
    
    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).with_for_update().first()

        if not db_user:
            await query.edit_message_text("❌ **KHÔNG TÌM THẤY TÀI KHOẢN**")
            return
        
        price = 3000

        if db_user.balance < price:
            await query.edit_message_text(
                f"❌ **SỐ DƯ KHÔNG ĐỦ!**\n\n"
                f"Cần {price}đ, bạn có {db_user.balance:,}đ",
                parse_mode='Markdown'
            )
            return
        
        try:
            url = f"{BASE_URL}/sim/reuse_by_phone_api_key"
            params = {
                'api_key': API_KEY,
                'phone': phone,
                'service_id': service_id
            }
            
            logger.info(f"🔄 Thuê lại số: phone={phone}, service_id={service_id}")

            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        await query.edit_message_text("❌ **API KHÔNG PHẢN HỒI HỢP LỆ**")
                        return
                    response_data = await response.json()

            if response_data.get('status') == 200:
                sim_data = response_data.get('data', {})
                new_otp_id = sim_data.get('otpId')
                new_sim_id = sim_data.get('simId')
                
                lock = await get_rental_lock(0)  # lock chung cho user khi reuse
                async with lock:
                    db_user.balance -= price
                    db_user.total_spent += price
                    db_user.total_rentals += 1
                
                service_name = "Unknown"
                services = await get_services()
                if services:
                    for sv in services:
                        if str(sv.get('id')) == service_id:
                            service_name = sv.get('name', 'Unknown')
                            break
                
                rental = Rental(
                    user_id=user.id,
                    service_id=int(service_id),
                    service_name=service_name,
                    phone_number=phone,
                    otp_id=new_otp_id,
                    sim_id=new_sim_id,
                    cost=price - 1000,
                    price_charged=price,
                    status='waiting',
                    created_at=get_vn_time(),
                    expires_at=get_vn_time() + timedelta(minutes=5)
                )

                db.session.add(rental)
                db.session.commit()
                
                logger.info(f"✅ Thuê lại số {phone} thành công")
                
                keyboard = [
                    [InlineKeyboardButton(f"📞 {phone}", callback_data=f"rent_view_{rental.id}")],
                    [InlineKeyboardButton("📋 DANH SÁCH SỐ", callback_data="menu_rent_list")],
                    [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
                ]

                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"✅ **THUÊ LẠI SỐ THÀNH CÔNG!**\n\n"
                    f"📞 **Số:** `{phone}`\n"
                    f"💰 **Đã thanh toán:** {price:,}đ\n"
                    f"💵 **Số dư còn lại:** {db_user.balance:,}đ",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                task = asyncio.create_task(
                    auto_check_otp_task(
                        context.bot,
                        update.effective_chat.id,
                        new_otp_id,
                        rental.id,
                        user.id,
                        service_name,
                        phone
                    )
                )
                auto_check_tasks[rental.id] = task
                
            else:
                await query.edit_message_text(
                    f"❌ **LỖI THUÊ LẠI**\n\n{response_data.get('message', 'Không rõ lỗi')}",
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Lỗi thuê lại: {e}")
            await query.edit_message_text("❌ **LỖI KẾT NỐI**\n\nVui lòng thử lại sau.")


async def rent_cancel_callback(update: Update, context: Context):
    """Hủy số - SIÊU BẢO VỆ CHỐNG CỘNG SAI"""
    query = update.callback_query
    await safe_answer_callback(query, "⏳ Đang hủy...")
    
    try:
        sim_id = query.data.split('_')[2]
        rental_id = int(query.data.split('_')[3])
    except Exception:
        await query.edit_message_text("❌ Lỗi dữ liệu")
        return
    
    # Hủy task auto-check nếu đang chạy
    if rental_id in auto_check_tasks:
        try:
            auto_check_tasks[rental_id].cancel()
            await asyncio.sleep(0.5)
        except:
            pass
        auto_check_tasks.pop(rental_id, None)
    
    # Gọi API cancel (không bắt buộc thành công)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/sim/cancel_api_key/{sim_id}?api_key={API_KEY}",
                timeout=8
            ) as resp:
                pass
    except Exception:
        pass
    
    # Hoàn tiền an toàn
    success = await safe_refund_rental(
        context.bot,
        rental_id,
        update.effective_chat.id,
        "",  # phone lấy trong hàm
        "cancel"
    )
    
    if not success:
        await query.edit_message_text("❌ Số này đã được xử lý trước đó hoặc không thể hủy.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🆕 THUÊ TIẾP", callback_data="menu_rent")],
        [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
    ]
    
    await query.edit_message_text(
        "✅ **ĐÃ HỦY SỐ THÀNH CÔNG!**\n\n"
        "💰 Tiền đã được hoàn lại đầy đủ vào số dư.\n"
        "Kiểm tra số dư trong menu Balance.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def rent_list_callback(update: Update, context: Context):
    """Hiển thị danh sách số đang thuê - CÓ NÚT HỦY CHO SỐ CHỜ OTP"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user = update.effective_user
    
    with app.app_context():
        waiting_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status == 'waiting',
            Rental.refunded == False
        ).order_by(Rental.created_at.desc()).all()
        
        recent_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status == 'completed'
        ).order_by(Rental.created_at.desc()).limit(10).all()
        
        old_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status.in_(['cancelled', 'expired'])
        ).order_by(Rental.created_at.desc()).limit(5).all()
    
    if query.message:
        try:
            await query.message.delete()
        except Exception:
            pass
    
    if not waiting_rentals and not recent_rentals and not old_rentals:
        keyboard = [[InlineKeyboardButton("📱 THUÊ SỐ NGAY", callback_data="menu_rent")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📭 **BẠN CHƯA THUÊ SỐ NÀO**\n\nHãy thuê số đầu tiên ngay!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    text = "📋 **DANH SÁCH SỐ CỦA BẠN**\n\n"
    keyboard = []
    
    if waiting_rentals:
        text += "🟢 **ĐANG CHỜ OTP:**\n"
        for rental in waiting_rentals:
            expires_in = int((rental.expires_at - get_vn_time()).total_seconds() / 60) if rental.expires_at else -1
            time_display = f"⏳ Còn {max(0, expires_in)} phút" if expires_in >= 0 else "Chờ OTP"
            
            text += f"• `{rental.phone_number}` - {rental.service_name} ({time_display})\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📞 {rental.phone_number}", 
                    callback_data=f"rent_view_{rental.id}"
                ),
                InlineKeyboardButton(
                    f"❌ HỦY", 
                    callback_data=f"rent_cancel_{rental.sim_id}_{rental.id}"
                )
            ])
        text += "\n"
    
    if recent_rentals:
        text += "✅ **ĐÃ NHẬN OTP GẦN ĐÂY:**\n"
        for rental in recent_rentals:
            otp_display = rental.otp_code or "Audio OTP"
            text += f"• `{rental.phone_number}` - {rental.service_name} - OTP: {otp_display}\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 THUÊ LẠI {rental.phone_number}",
                    callback_data=f"rent_reuse_{rental.phone_number}_{rental.service_id}"
                )
            ])
        text += "\n"
    
    if old_rentals:
        text += "⏰ **ĐÃ HẾT HẠN/HỦY:**\n"
        for rental in old_rentals:
            status_icon = "❌" if rental.status == 'cancelled' else "⏰"
            text += f"• {status_icon} `{rental.phone_number}` - {rental.service_name}\n"
    
    keyboard.append([InlineKeyboardButton("🆕 THUÊ SỐ MỚI", callback_data="menu_rent")])
    keyboard.append([InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )