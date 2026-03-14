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
async def push_balance_async(user_id, balance, username):
    """Push balance lên Render bằng async - KHÔNG DÍNH VẠCH VÀNG"""
    try:
        RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-new.onrender.com')
        push_data = {
            'user_id': user_id,
            'balance': balance,
            'username': username
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{RENDER_URL}/api/sync-bidirectional",
                json=push_data,
                timeout=3
            ) as response:
                if response.status == 200:
                    logger.info(f"📤 Push balance thành công: {balance}đ")
                else:
                    logger.warning(f"⚠️ Push thất bại: {response.status}")
    except Exception as e:
        logger.error(f"❌ Lỗi push: {e}")


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

# ==================== CORE ====================

async def delete_previous_menu(update: Update, context: Context):
    """Xóa menu trước đó để tránh nhiều menu chồng lên nhau"""
    try:
        if update and update.callback_query and update.callback_query.message:
            await safe_delete_message(update.callback_query.message)

        elif update and update.message:
            await safe_delete_message(update.message)

    except Exception as e:
        logger.error(f"Lỗi xóa menu cũ: {e}")

# ==================== API ====================

async def get_services():
    """Lấy danh sách dịch vụ từ API"""
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

                    try:
                        data = await response.json()
                    except Exception:
                        logger.error("API services trả dữ liệu không phải JSON")
                        return []

            if isinstance(data, dict) and data.get('status') == 200:
                services_cache = data.get('data', [])
                services_cache_time = time.time()
                return services_cache

            else:
                logger.error(f"Lỗi API services: {data}")
                return []

        except asyncio.TimeoutError:
            logger.error("API services timeout")
            return []

        except Exception as e:
            logger.error(f"Lỗi kết nối API services: {e}")
            return []

async def get_networks():
    """Lấy danh sách nhà mạng từ API"""
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

                    try:
                        data = await response.json()
                    except Exception:
                        logger.error("API networks trả dữ liệu không phải JSON")
                        return []

            if isinstance(data, dict) and data.get('status') == 200:

                networks_cache = data.get('data', [])
                networks_cache_time = time.time()

                return networks_cache

            else:
                logger.error(f"Lỗi API networks: {data}")
                return []

        except asyncio.TimeoutError:
            logger.error("API networks timeout")
            return []

        except Exception as e:
            logger.error(f"Lỗi kết nối API networks: {e}")
            return []

async def get_account_info():
    """Lấy thông tin tài khoản API"""
    try:

        url = f"{BASE_URL}/yourself/information-by-api-key?api_key={API_KEY}"

        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return None

                try:
                    data = await response.json()
                except Exception:
                    return None

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

        is_banned = False

        for banned in banned_services:
            if banned in name_upper:
                is_banned = True
                break

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

    total_services = len(filtered_services)

    text = (
        f"📱 **THUÊ SỐ NHẬN OTP**\n\n"
        f"📊 **Tổng số dịch vụ:** {total_services}\n\n"
        f"⚠️ **TUÂN THỦ PHÁP LUẬT:**\n"
        f"• Nghiêm cấm đánh bạc, cá độ, lừa đảo\n"
        f"• Nghiêm cấm tạo bank ảo, tiền ảo\n"
        f"• Dịch vụ ZALO, Telegram hiện đang CẤM!\n"
        f"• Mọi vi phạm sẽ khóa tài khoản vĩnh viễn\n\n"
        f"👇 **Chọn dịch vụ bên dưới:**"
    )

    await loading_msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def rent_service_callback(update: Update, context: Context):
    """Xử lý khi chọn dịch vụ"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_')
        service_id = data[2]
        service_name = data[3]
        original_price = int(float(data[4]))
        final_price = original_price + 1000
    except Exception as e:
        logger.error(f"Lỗi parse data: {e}")
        await safe_edit_message(query, "❌ **LỖI DỮ LIỆU**\n\nVui lòng chọn lại dịch vụ.")
        return
    
    context.user_data['rent'] = {
        'service_id': service_id,
        'service_name': service_name,
        'final_price': final_price,
        'original_price': original_price
    }
    
    if query.message:
        await safe_delete_message(query.message)
    
    loading_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ **ĐANG TẢI DANH SÁCH NHÀ MẠNG...**",
        parse_mode='Markdown'
    )
    
    try:
        networks = await get_networks()
    except Exception as e:
        logger.error(f"Lỗi get_networks: {e}")
        networks = []
    
    if not networks:
        keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await loading_msg.edit_text(
            "❌ **KHÔNG THỂ LẤY DANH SÁCH NHÀ MẠNG**\n\nVui lòng thử lại sau.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    active_networks = [net for net in networks if net.get('status') == 1]
    
    if not active_networks:
        keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await loading_msg.edit_text(
            "⚠️ **KHÔNG CÓ NHÀ MẠNG NÀO HOẠT ĐỘNG**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    keyboard = []
    for net in active_networks[:10]:
        net_id = net.get('id')
        net_name = net.get('name')
        if not net_id or not net_name:
            continue

        keyboard.append([
            InlineKeyboardButton(
                f"📶 {net_name}",
                callback_data=f"rent_network_{net_id}_{net_name}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"📱 **{service_name}**\n"
        f"📶 **Chọn nhà mạng:**"
    )
    
    try:
        await loading_msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Lỗi edit message: {e}")


async def rent_network_callback(update: Update, context: Context):
    """Xử lý khi chọn nhà mạng"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_')
        network_id = data[2]
        network_name = data[3]
    except Exception as e:
        logger.error(f"Lỗi parse network: {e}")
        await safe_edit_message(query, "❌ **LỖI DỮ LIỆU**\n\nVui lòng chọn lại.")
        return
    
    rent_info = context.user_data.get('rent', {})
    service_id = rent_info.get('service_id')
    service_name = rent_info.get('service_name')
    final_price = rent_info.get('final_price')
    original_price = rent_info.get('original_price')
    
    if not service_id or final_price is None:
        await safe_edit_message(query, "❌ **LỖI!**\n\nVui lòng chọn lại dịch vụ.")
        return
    
    user = update.effective_user
    
    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).first()
        current_balance = db_user.balance if db_user else 0
    
    if query.message:
        await safe_delete_message(query.message)
    
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ XÁC NHẬN THUÊ",
                callback_data=f"rent_confirm_{service_id}_{final_price}_{network_id}"
            )
        ],
        [
            InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"📱 **XÁC NHẬN THUÊ SỐ**\n\n"
        f"• **Dịch vụ:** {service_name}\n"
        f"• **Nhà mạng:** {network_name}\n"
        f"• **Số dư của bạn:** {current_balance:,}đ\n\n"
        f"📌 **Lưu ý:**\n"
        f"• Số tiền sẽ được trừ ngay sau khi xác nhận\n"
        f"• Có thể hủy và được hoàn tiền nếu chưa nhận OTP\n"
        f"• Số có hiệu lực trong 10 phút\n\n"
        f"❓ **Xác nhận thuê số?**"
    )
    
    await safe_send_message(
        context,
        update.effective_chat.id,
        text,
        reply_markup
    )

async def rent_confirm_callback(update: Update, context: Context):
    """Xác nhận thuê số - LOCAL TRƯỚC, RENDER SAU"""
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

                db_user = User.query.filter_by(user_id=user.id).with_for_update().first()
                
                if db_user.balance < final_price:
                    await loading_msg.edit_text("❌ **SỐ DƯ KHÔNG ĐỦ**\n\nSố dư đã thay đổi, vui lòng thử lại.")
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
                    created_at=datetime.now(),
                    expires_at=datetime.now() + timedelta(minutes=10)
                )
                db.session.add(rental)
                
                old_balance = db_user.balance
                db_user.balance -= final_price
                db_user.total_spent += final_price
                db_user.total_rentals += 1
                db_user.updated_at = datetime.now()
                
                # ===== BƯỚC 1: CẬP NHẬT LOCAL NGAY =====
                db.session.commit()
                db.session.refresh(db_user)
                
                logger.info(f"✅ LOCAL UPDATE: User {user.id}: {old_balance}đ → {db_user.balance}đ")
                
                # ===== BƯỚC 2: PUSH LÊN RENDER (KHÔNG CHỜ) =====
                asyncio.create_task(push_balance_async(
                    user.id, 
                    db_user.balance, 
                    user.username or f"user_{user.id}"
                ))
                
                if 'rent' in context.user_data:
                    del context.user_data['rent']

                keyboard = [
                    [InlineKeyboardButton(f"📞 {phone} - {rent_info['service_name']}", callback_data=f"rent_view_{rental.id}")],
                    [InlineKeyboardButton("📋 DANH SÁCH SỐ", callback_data="menu_rent_list")],
                    [InlineKeyboardButton("🆕 THUÊ SỐ KHÁC", callback_data="menu_rent")],
                    [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
                ]

                # Sau khi commit thành công và push lên Render
                await loading_msg.edit_text(
                    f"✅ **THUÊ SỐ THÀNH CÔNG!**\n\n"
                    f"📞 **Số:** `{phone}`\n"
                    f"📱 **Dịch vụ:** {rent_info['service_name']}\n"
                    f"💰 **Đã thanh toán:** {final_price:,}đ\n"
                    f"💵 **Số dư còn lại:** {db_user.balance:,}đ\n\n"
                    f"⏳ **Vui lòng chờ, hệ thống sẽ tự động gửi OTP cho quý khách khi nhận được!**\n"
                    f"🤖 Bot sẽ tự động kiểm tra OTP trong vài phút tới.\n\n"
                    f"📌 Bạn có thể kiểm tra OTP thủ công bằng nút '🔍 KIỂM TRA OTP'.",
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
            error_code = response_data.get('code', '')
            
            # Log chi tiết
            logger.error(f"❌ API trả lỗi: code={error_code}, message={error_msg}")
            logger.error(f"   Full response: {response_data}")
            
            # Hiển thị cho user
            display_msg = f"❌ {error_msg}"
            if error_code:
                display_msg = f"❌ [{error_code}] {error_msg}"
            
            await loading_msg.edit_text(
                f"❌ **LỖI TỪ SERVER**\n\n"
                f"📢 {display_msg}\n\n"
                f"💡 Sim quý khách vừa chọn đã hết vui lòng chọn sim khác.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")
                ]]),
                parse_mode='Markdown'
            )

    except asyncio.TimeoutError:
        await loading_msg.edit_text("⏰ **TIMEOUT API**\n\nThử lại sau.")
    except Exception as e:
        logger.error(f"❌ Lỗi thuê số: {e}")
        await loading_msg.edit_text("❌ **LỖI KẾT NỐI**\n\nThử lại sau.")

async def rent_check_callback(update: Update, context: Context):
    """Kiểm tra OTP thủ công - GỬI CẢ TEXT VÀ AUDIO"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_',3)
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
        params = {'api_key': API_KEY,'otp_id': otp_id}
        
        logger.info(f"🔍 Kiểm tra OTP cho otp_id={otp_id}")
        
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url,params=params) as response:
                try:
                    response_data = await response.json()
                except:
                    logger.error("API OTP trả JSON lỗi")
                    await query.edit_message_text("❌ **LỖI API**")
                    return
        
        logger.info(f"API check OTP response: {response_data}")
        
        with app.app_context():
            rental = Rental.query.get(rental_id)
            
            if not rental:
                await query.edit_message_text(
                    "❌ **KHÔNG TÌM THẤY THÔNG TIN THUÊ SỐ**\n\n"
                    "Vui lòng thử lại hoặc liên hệ admin.",
                    parse_mode='Markdown'
                )
                return
            
            status = response_data.get('status')
            
            if status == 200:
                otp_data = response_data.get('data', {})
                otp_code = otp_data.get('code')
                content = otp_data.get('content','')
                sender = otp_data.get('senderName','')
                audio_url = otp_data.get('audio')
                
                rental.status='success'
                rental.otp_code=otp_code or "Audio OTP"
                rental.status="completed"
                rental.content=content
                rental.updated_at=datetime.now()
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
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(audio_url,headers={'User-Agent':'Mozilla/5.0'}) as audio_response:
                                
                                if audio_response.status==200:
                                    audio_bytes=await audio_response.read()
                                    
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
                
            elif status==202:
                expires_in=int((rental.expires_at-datetime.now()).total_seconds()/60)
                await query.edit_message_text(
                    f"⏳ **CHƯA CÓ OTP**\n\n• Còn {expires_in} phút",
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
    """Tự động kiểm tra OTP - SIÊU BẢO VỆ + GỬI CẢ TEXT VÀ AUDIO + CHỐNG CỘNG TRỪ SAI"""
    logger.info(f"🤖 Bắt đầu auto-check OTP cho rental {rental_id}")
    
    max_checks = 120
    check_count = 0
    processed = False
    
    try:
        while check_count < max_checks and not processed:

            # === KIỂM TRA HẾT HẠN ===
            with app.app_context():
                rental = Rental.query.filter_by(id=rental_id).with_for_update().first()

                if rental and rental.status == 'waiting' and not rental.refunded and not rental.otp_code:
                    now = datetime.now()

                    if now > rental.expires_at:

                        if rental.refunded:
                            return

                        logger.info(f"⏰ Rental {rental_id} đã hết hạn (timeout)")

                        refund = rental.price_charged
                        user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()

                        if user:

                            user.balance += refund

                            rental.status = 'expired'
                            rental.refunded = True
                            rental.refund_amount = refund
                            rental.refunded_at = now

                            try:
                                db.session.commit()
                            except Exception as db_error:
                                db.session.rollback()
                                logger.error(f"DB error refund: {db_error}")
                                return

                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                     f"📞 Số `{phone}` đã hết hạn.\n"
                                     f"💰 **Đã hoàn lại {refund:,}đ!**\n"
                                     f"💵 **Số dư mới:** {user.balance:,}đ",
                                parse_mode='Markdown'
                            )

                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]

                            return

            task = asyncio.current_task()
            if task and task.cancelled():
                logger.info(f"🛑 Task {rental_id} bị hủy")
                return

            check_count += 1
            logger.info(f"🔄 Auto-check OTP {check_count}/{max_checks} rental {rental_id}")

            try:

                with app.app_context():

                    rental = Rental.query.filter_by(id=rental_id).with_for_update().first()

                    if not rental:
                        return

                    if rental.refunded:
                        return

                    if rental.status in ['cancelled', 'expired', 'completed']:
                        return

                # ===== API CHECK OTP =====

                url = f"{BASE_URL}/otp/get_otp_by_phone_api_key"
                params = {'api_key': API_KEY, 'otp_id': otp_id}

                try:
                    response = requests.get(url, params=params, timeout=5)
                except Exception as req_err:
                    logger.error(f"API request error: {req_err}")
                    await asyncio.sleep(5)
                    continue

                if response.status_code != 200:
                    await asyncio.sleep(5)
                    continue

                try:
                    response_data = response.json()
                except Exception:
                    logger.error("API JSON decode error")
                    await asyncio.sleep(5)
                    continue

                status = response_data.get('status')

                # ===== CÓ OTP =====
                if status == 200:

                    otp_data = response_data.get('data', {})
                    otp_code = otp_data.get('code')
                    content = otp_data.get('content', '')
                    audio_url = otp_data.get('audio')

                    with app.app_context():

                        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()

                        if rental and rental.status == 'waiting' and not rental.refunded and not rental.otp_code:

                            rental.status = "completed"
                            rental.otp_code = otp_code or "Audio OTP"
                            rental.content = content
                            rental.updated_at = datetime.now()

                            try:
                                db.session.commit()
                            except Exception as db_error:
                                db.session.rollback()
                                logger.error(f"DB commit error: {db_error}")
                                return

                            processed = True

                            if otp_code:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"🔑 **MÃ OTP:** `{otp_code}`\n📝 {content}\n📱 **Dịch vụ:** {service_name}\n📞 **Số:** `{phone}`",
                                    parse_mode='Markdown'
                                )

                            if audio_url:

                                try:

                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text="⏳ **ĐANG TẢI AUDIO OTP...**",
                                        parse_mode='Markdown'
                                    )

                                    headers = {'User-Agent': 'Mozilla/5.0'}
                                    audio_response = requests.get(audio_url, headers=headers, timeout=30)

                                    if audio_response.status_code == 200:

                                        await bot.send_audio(
                                            chat_id=chat_id,
                                            audio=audio_response.content,
                                            filename=f"otp_audio_{rental_id}.mp3",
                                            title=f"OTP Audio - {service_name}",
                                            caption=f"📱 {service_name}\n📞 `{phone}`",
                                            parse_mode='Markdown'
                                        )

                                    else:

                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=f"🔊 **LINK AUDIO OTP**\n\n"
                                                 f"[Nghe tại đây]({audio_url})",
                                            parse_mode='Markdown'
                                        )

                                except Exception as e:
                                    logger.error(f"Lỗi tải audio: {e}")

                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]

                            return

                elif status in [202, 312]:

                    # vẫn đang chờ OTP
                    pass

                elif status == 400:

                    # ⚠ FIX LỖI: KHÔNG REFUND KHI API TRẢ 400
                    logger.info(f"⚠ API trả 400 cho rental {rental_id}, tiếp tục chờ OTP")

                    await asyncio.sleep(5)
                    continue

            except Exception as e:
                logger.error(f"Lỗi auto-check: {e}")

            await asyncio.sleep(5)

        # ===== HẾT VÒNG LẶP =====

        if not processed:

            with app.app_context():

                rental = Rental.query.filter_by(id=rental_id).with_for_update().first()

                if rental and rental.status == 'waiting' and not rental.refunded and not rental.otp_code:

                    now = datetime.now()

                    if now < rental.expires_at:
                        return

                    user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()

                    if user:

                        refund = rental.price_charged

                        user.balance += refund

                        rental.status = 'expired'
                        rental.refunded = True
                        rental.refund_amount = refund
                        rental.refunded_at = now

                        try:
                            db.session.commit()
                        except Exception as db_error:
                            db.session.rollback()
                            logger.error(db_error)
                            return

                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                 f"📞 `{phone}` đã hết thời gian chờ OTP.\n"
                                 f"💰 **Đã hoàn lại {refund:,}đ**\n"
                                 f"💵 **Số dư mới:** {user.balance:,}đ",
                            parse_mode='Markdown'
                        )

            if rental_id in auto_check_tasks:
                del auto_check_tasks[rental_id]

    except asyncio.CancelledError:

        logger.info(f"🛑 Task {rental_id} bị hủy")

        if rental_id in auto_check_tasks:
            del auto_check_tasks[rental_id]

        raise

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
            expires_in = int((rental.expires_at - datetime.now()).total_seconds() / 60)
        except Exception:
            expires_in = 0

        if expires_in < 0:
            expires_in = 0
            
        status_text = {
            'waiting': f'⏳ Đang chờ OTP (còn {expires_in} phút)',
            'success': '✅ Đã nhận OTP',
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

        elif rental.status == 'success':
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
    """Thuê lại số đã từng thuê thành công + PUSH LÊN RENDER"""
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

        db_user = User.query.filter_by(user_id=user.id).first()

        if not db_user:
            await query.edit_message_text("❌ **KHÔNG TÌM THẤY TÀI KHOẢN**")
            return
        
        price = 3000

        if db_user.balance < price:
            await query.edit_message_text(
                f"❌ **SỐ DƯ KHÔNG ĐỦ!**\n\n"
                f"Cần {price}đ, bạn có {db_user.balance}đ",
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

            try:
                response = requests.get(url, params=params, timeout=15)
            except Exception as req_error:
                logger.error(f"API request error: {req_error}")
                await query.edit_message_text(
                    "❌ **LỖI KẾT NỐI API**",
                    parse_mode='Markdown'
                )
                return

            if response.status_code != 200:
                await query.edit_message_text(
                    "❌ **API KHÔNG PHẢN HỒI HỢP LỆ**",
                    parse_mode='Markdown'
                )
                return

            try:
                response_data = response.json()
            except Exception:
                await query.edit_message_text(
                    "❌ **LỖI DỮ LIỆU API**",
                    parse_mode='Markdown'
                )
                return
            
            if response_data.get('status') == 200:

                sim_data = response_data.get('data', {})
                new_otp_id = sim_data.get('otpId')
                new_sim_id = sim_data.get('simId')
                
                old_balance = db_user.balance

                db_user.balance -= price
                db_user.total_spent += price
                db_user.total_rentals += 1
                
                service_name = "Unknown"

                services = await get_services()

                if services:
                    for sv in services:
                        try:
                            if str(sv['id']) == service_id:
                                service_name = sv['name']
                                break
                        except Exception:
                            continue
                
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
                    created_at=datetime.now(),
                    expires_at=datetime.now() + timedelta(minutes=10)
                )

                db.session.add(rental)

                try:
                    db.session.commit()
                    
                    # ===== PUSH LÊN RENDER BẰNG ASYNC =====
                    asyncio.create_task(push_balance_async(
                        user.id,
                        db_user.balance,
                        user.username or f"user_{user.id}"
                    ))
                    
                except Exception as db_error:
                    db.session.rollback()
                    logger.error(f"DB commit error: {db_error}")
                    await query.edit_message_text(
                        "❌ **LỖI LƯU DỮ LIỆU**",
                        parse_mode='Markdown'
                    )
                    return
                
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
                    f"📱 **Dịch vụ:** {service_name}\n"
                    f"💰 **Đã thanh toán:** {price:,}đ\n"
                    f"💵 **Số dư còn lại:** {db_user.balance:,}đ\n\n"
                    f"⏳ **Vui lòng chờ, hệ thống sẽ tự động gửi OTP cho quý khách khi nhận được!**\n"
                    f"🤖 Bot sẽ tự động kiểm tra OTP trong vài phút tới.\n\n"
                    f"📌 Bạn có thể kiểm tra OTP thủ công bằng nút '🔍 KIỂM TRA OTP'.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                task = asyncio.create_task(
                    auto_check_otp_task(
                        context.bot,
                        chat_id=update.effective_chat.id,
                        otp_id=new_otp_id,
                        rental_id=rental.id,
                        user_id=user.id,
                        service_name=service_name,
                        phone=phone
                    )
                )

                auto_check_tasks[rental.id] = task
                
            else:
                await query.edit_message_text(
                    f"❌ **LỖI THUÊ LẠI**\n\n{response_data.get('message', 'Không rõ lỗi')}",
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Lỗi thuê lại: {e}")

            await query.edit_message_text(
                "❌ **LỖI KẾT NỐI**\n\nVui lòng thử lại sau.",
                parse_mode='Markdown'
            )
async def rent_cancel_callback(update: Update, context: Context):
    """Hủy số - LOCAL TRƯỚC, RENDER SAU"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_')
        sim_id = data[2]
        rental_id = int(data[3])
    except Exception as e:
        logger.error(f"Lỗi parse cancel: {e}")
        await query.edit_message_text("❌ **LỖI DỮ LIỆU**")
        return
    
    if rental_id in auto_check_tasks:
        logger.info(f"⏳ Đang có task auto-check cho rental {rental_id}, chờ kết thúc...")
        for _ in range(10):
            if rental_id not in auto_check_tasks:
                break
            await asyncio.sleep(0.2)

    with app.app_context():
        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
        
        if not rental:
            await query.edit_message_text("❌ **KHÔNG TÌM THẤY GIAO DỊCH**")
            return
        
        user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()
        
        if not user:
            await query.edit_message_text("❌ **KHÔNG TÌM THẤY USER**")
            return
        
        if rental.refunded:
            await query.edit_message_text(
                f"❌ **SỐ NÀY ĐÃ ĐƯỢC HOÀN {rental.refund_amount}đ**\n\n"
                f"✅ Mỗi số chỉ được hoàn 1 lần!",
                parse_mode='Markdown'
            )
            return
        
        refund_amount = rental.price_charged
        expected_balance = user.balance + refund_amount
        
        if rental.status in ['completed', 'expired', 'cancelled']:
            await query.edit_message_text("❌ **ĐÃ NHẬN OTP**\n\nKhông thể hủy.")
            return
        
        if rental_id in auto_check_tasks:
            try:
                auto_check_tasks[rental_id].cancel()
                await asyncio.sleep(0.3)
                auto_check_tasks.pop(rental_id, None)
            except Exception as e:
                logger.error(f"Lỗi hủy task: {e}")
        
        try:
            url = f"{BASE_URL}/sim/cancel_api_key/{sim_id}?api_key={API_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    api_data = await response.json()

            api_success = api_data.get('status') == 200
            
            db.session.refresh(user)
            db.session.refresh(rental)
            
            if rental.refunded:
                db.session.rollback()
                await query.edit_message_text("❌ Giao dịch đã được xử lý trước đó")
                return
            
            old_balance = user.balance
            
            rental.status = 'cancelled'
            rental.refunded = True
            rental.refund_amount = refund_amount
            rental.refunded_at = get_vn_time()

            if api_success:
                # ===== BƯỚC 1: CẬP NHẬT LOCAL NGAY =====
                user.balance += refund_amount
                db.session.commit()
                
                logger.info(f"✅ LOCAL UPDATE: User {user.user_id}: {old_balance}đ → {user.balance}đ")
                
                # ===== BƯỚC 2: PUSH LÊN RENDER (KHÔNG CHỜ) =====
                asyncio.create_task(push_balance_async(
                    user.user_id,
                    user.balance,
                    user.username or f"user_{user.user_id}"
                ))
                
                keyboard = [
                    [InlineKeyboardButton("🆕 THUÊ TIẾP", callback_data="menu_rent")],
                    [InlineKeyboardButton("💰 XEM SỐ DƯ", callback_data="menu_balance")],
                    [InlineKeyboardButton("🔙 MENU", callback_data="menu_main")]
                ]
                
                await query.edit_message_text(
                    f"✅ **HỦY SỐ THÀNH CÔNG!**\n\n"
                    f"📞 **Số:** {rental.phone_number}\n"
                    f"💰 **Hoàn tiền:** {refund_amount:,}đ\n"
                    f"💵 **Số dư mới:** {user.balance:,}đ",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ Không thể hủy số từ server.")
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ LỖI: {e}")
            await query.edit_message_text(f"❌ **LỖI**\n\n{str(e)}")
async def rent_list_callback(update: Update, context: Context):
    """Hiển thị danh sách số đang thuê - HIỂN THỊ 20 SỐ THÀNH CÔNG GẦN NHẤT"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user = update.effective_user
    
    with app.app_context():
        # Số đang chờ OTP
        waiting_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status == 'waiting',
            Rental.refunded == False
        ).order_by(Rental.created_at.desc()).all()
        
        # ===== ĐÃ SỬA: TĂNG LIMIT LÊN 20 SỐ THÀNH CÔNG GẦN NHẤT =====
        recent_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status.in_(['completed', 'success'])
        ).order_by(Rental.created_at.desc()).limit(20).all()  # <--- TĂNG LÊN 20
        
        # Số đã hủy/hết hạn (giữ 5 số)
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
    
    # HIỂN THỊ SỐ ĐANG CHỜ OTP
    if waiting_rentals:
        text += "🟢 **ĐANG CHỜ OTP:**\n"
        for rental in waiting_rentals:
            if rental.expires_at:
                expires_in = int((rental.expires_at - get_vn_time()).total_seconds() / 60)
            else:
                expires_in = -1

            if expires_in < 0:
                time_display = "Chờ OTP"
            else:
                time_display = f"⏳ Còn {expires_in} phút"
            
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
    
    # ===== ĐÃ SỬA: HIỂN THỊ 20 SỐ THÀNH CÔNG GẦN NHẤT =====
    if recent_rentals:
        text += f"✅ **ĐÃ NHẬN OTP (20 SỐ GẦN NHẤT):**\n"
        for rental in recent_rentals:
            otp_display = rental.otp_code or "Audio OTP"
            # Cắt ngắn OTP nếu quá dài
            if len(otp_display) > 10:
                otp_display = otp_display[:10] + "..."
            
            text += f"• `{rental.phone_number}` - {rental.service_name} - OTP: {otp_display}\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 THUÊ LẠI {rental.phone_number}",
                    callback_data=f"rent_reuse_{rental.phone_number}_{rental.service_id}"
                )
            ])
        text += f"\n📌 *Hiển thị {len(recent_rentals)}/20 số thành công gần nhất*\n\n"
    
    # HIỂN THỊ SỐ ĐÃ HỦY/HẾT HẠN
    if old_rentals:
        text += "⏰ **ĐÃ HẾT HẠN/HỦY (5 số gần nhất):**\n"
        for rental in old_rentals:
            status_icon = "❌" if rental.status == 'cancelled' else "⏰"
            text += f"• {status_icon} `{rental.phone_number}` - {rental.service_name}\n"
        text += "\n"
    
    # NÚT ĐIỀU HƯỚNG
    keyboard.append([InlineKeyboardButton("🆕 THUÊ SỐ MỚI", callback_data="menu_rent")])
    keyboard.append([InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )