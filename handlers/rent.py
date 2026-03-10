from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot import app
from telegram.ext import CallbackContext as Context
from database.models import User, Rental, BalanceLog, db
from datetime import datetime, timedelta
from datetime import datetime, timedelta, timezone
import requests
import os
import logging
import time
import asyncio
from typing import Dict

VN_TZ = timezone(timedelta(hours=7))
def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

logger = logging.getLogger(__name__)

API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL')

# Cache để tránh gọi API quá nhiều
services_cache = []
services_cache_time = 0
networks_cache = []
networks_cache_time = 0

# Dictionary để lưu trữ các task auto-check OTP
auto_check_tasks: Dict[int, asyncio.Task] = {}

# ==================== HÀM TIỆN ÍCH TỐI ƯU ====================
async def safe_answer_callback(query, text=None, show_alert=False):
    """Answer callback an toàn"""
    try:
        await query.answer(text=text, show_alert=show_alert, cache_time=0)
    except Exception as e:
        logger.debug(f"Answer callback error: {e}")

async def safe_edit_message(query, text, reply_markup=None, parse_mode='Markdown', max_retries=2):
    """Sửa tin nhắn an toàn, tự động retry"""
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

async def safe_delete_message(message):
    """Xóa tin nhắn an toàn"""
    try:
        await message.delete()
    except Exception as e:
        logger.debug(f"Delete message failed: {e}")

# ==================== HÀM CACHE ====================
def get_cached_services():
    """Lấy services từ cache"""
    global services_cache, services_cache_time
    if services_cache and time.time() - services_cache_time < 300:
        return services_cache
    return None

def get_cached_networks():
    """Lấy networks từ cache"""
    global networks_cache, networks_cache_time
    if networks_cache and time.time() - networks_cache_time < 300:
        return networks_cache
    return None

# ==================== HÀM GỐC (GIỮ NGUYÊN) ====================
async def delete_previous_menu(update: Update, context: Context):
    """Xóa menu trước đó để tránh nhiều menu chồng lên nhau"""
    try:
        if update.callback_query and update.callback_query.message:
            await safe_delete_message(update.callback_query.message)
    except Exception as e:
        logger.error(f"Lỗi xóa menu cũ: {e}")

async def get_services():
    """Lấy danh sách dịch vụ từ API"""
    global services_cache, services_cache_time
    
    # Kiểm tra cache trước
    cached = get_cached_services()
    if cached:
        return cached
    
    try:
        url = f"{BASE_URL}/service/get_service_by_api_key?api_key={API_KEY}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('status') == 200:
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
    """Lấy danh sách nhà mạng từ API"""
    global networks_cache, networks_cache_time
    
    # Kiểm tra cache trước
    cached = get_cached_networks()
    if cached:
        return cached
    
    try:
        url = f"{BASE_URL}/network/get-network-by-api-key?api_key={API_KEY}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('status') == 200:
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
    """Lấy thông tin tài khoản API"""
    try:
        url = f"{BASE_URL}/yourself/information-by-api-key?api_key={API_KEY}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('status') == 200:
            return data.get('data', {})
        return None
    except Exception as e:
        logger.error(f"Lỗi lấy thông tin tài khoản: {e}")
        return None

async def rent_command(update: Update, context: Context):
    """Hiển thị danh sách dịch vụ (đã ẩn số dư API)"""
    logger.info("📱 rent_command được gọi")
    
    # Answer ngay để chống lag
    if update.callback_query:
        await safe_answer_callback(update.callback_query, "📱 Đang tải...")
    
    # Xóa menu cũ trước khi hiển thị menu mới
    await delete_previous_menu(update, context)
    
    # Kiểm tra user có bị ban không
    user = update.effective_user
    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).first()
        if db_user and db_user.is_banned:
            text = "❌ **TÀI KHOẢN CỦA BẠN ĐÃ BỊ KHÓA**\n\nVui lòng liên hệ admin để biết thêm chi tiết."
            await safe_send_message(context, update.effective_chat.id, text)
            return
    
    # Hiển thị trạng thái đang tải
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
    
    # Lọc các dịch vụ bị cấm
    banned_services = ['ZALO', 'TELEGRAM', 'BANK', 'TIENAO', 'CRYPTO']
    filtered_services = []
    for sv in services:
        name_upper = sv['name'].upper()
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
    
    # Tạo keyboard với giá đã cộng 1000đ - HIỂN THỊ TẤT CẢ DỊCH VỤ
    keyboard = []
    row = []
    for i, sv in enumerate(filtered_services):
        try:
            original_price = int(float(sv['price']))
            final_price = original_price + 1000
        except:
            original_price = 1200
            final_price = 2200
            
        button = InlineKeyboardButton(
            f"{sv['name']} - {final_price:,}đ",
            callback_data=f"rent_service_{sv['id']}_{sv['name']}_{original_price}"
        )
        row.append(button)
        
        # 2 nút trên 1 hàng
        if len(row) == 2:
            keyboard.append(row)
            row = []
    
    # Thêm hàng cuối cùng nếu còn
    if row:
        keyboard.append(row)
    
    # Thêm nút điều hướng
    keyboard.append([InlineKeyboardButton("📋 DANH SÁCH SỐ CỦA TÔI", callback_data="menu_rent_list")])
    keyboard.append([InlineKeyboardButton("🔙 QUAY LẠI MENU", callback_data="menu_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Đếm số dịch vụ
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
    
    # Lưu thông tin dịch vụ đã chọn
    context.user_data['rent'] = {
        'service_id': service_id,
        'service_name': service_name,
        'final_price': final_price,
        'original_price': original_price
    }
    
    # Xóa menu hiện tại
    await safe_delete_message(query.message)
    
    # Hiển thị trạng thái đang tải
    loading_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ **ĐANG TẢI DANH SÁCH NHÀ MẠNG...**",
        parse_mode='Markdown'
    )
    
    networks = await get_networks()
    
    if not networks:
        keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await loading_msg.edit_text(
            "❌ **KHÔNG THỂ LẤY DANH SÁCH NHÀ MẠNG**\n\nVui lòng thử lại sau.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Lọc nhà mạng đang hoạt động
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
        keyboard.append([InlineKeyboardButton(
            f"📶 {net['name']}",
            callback_data=f"rent_network_{net['id']}_{net['name']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"📱 **{service_name}**\n"
        f"📶 **Chọn nhà mạng:**"
    )
    
    await loading_msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')

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
    
    if not service_id or not final_price:
        await safe_edit_message(query, "❌ **LỖI!**\n\nVui lòng chọn lại dịch vụ.")
        return
    
    user = update.effective_user
    with app.app_context():
        db_user = User.query.filter_by(user_id=user.id).first()
        current_balance = db_user.balance if db_user else 0
    
    # Xóa menu hiện tại
    await safe_delete_message(query.message)
    
    keyboard = [
        [InlineKeyboardButton("✅ XÁC NHẬN THUÊ", callback_data=f"rent_confirm_{service_id}_{final_price}_{network_id}")],
        [InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]
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
        f"• Số có hiệu lực trong 5 phút\n\n"
        f"❓ **Xác nhận thuê số?**"
    )
    
    await safe_send_message(context, update.effective_chat.id, text, reply_markup)

async def rent_confirm_callback(update: Update, context: Context):
    """Xác nhận thuê số - Gọi API lấy số (ĐÃ FIX LỖI CỘNG TRỪ KHI THUÊ LIÊN TỤC)"""
    query = update.callback_query
    await safe_answer_callback(query, "⏳ Đang xử lý...")
    
    try:
        data = query.data.split('_')
        service_id = data[2]
        final_price = int(data[3])
        network_id = data[4]
    except Exception as e:
        logger.error(f"Lỗi parse confirm: {e}")
        await safe_edit_message(query, "❌ **LỖI DỮ LIỆU**\n\nVui lòng chọn lại.")
        return
    
    # ===== KIỂM TRA API KEY =====
    if not API_KEY or not BASE_URL:
        await safe_edit_message(query, "❌ **LỖI CẤU HÌNH**\n\nVui lòng liên hệ admin.")
        return
    
    user = update.effective_user
    
    with app.app_context():
        # ===== LẤY USER MỚI NHẤT VỚI KHÓA =====
        db_user = User.query.filter_by(user_id=user.id).with_for_update().first()
        
        logger.info(f"🔍 [BẮT ĐẦU] User {user.id} - Số dư từ DB: {db_user.balance if db_user else 0}đ")
        
        if not db_user:
            await safe_edit_message(query, "❌ **KHÔNG TÌM THẤY TÀI KHOẢN**\n\nVui lòng gửi /start để đăng ký.")
            return
        
        # ===== KIỂM TRA GIAO DỊCH GẦN ĐÂY (CHỐNG SPAM) =====
        recent_transactions = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.created_at > datetime.now() - timedelta(seconds=10)
        ).count()
        
        if recent_transactions > 3:
            logger.warning(f"⚠️ User {user.id} đang thuê quá nhanh: {recent_transactions} lần/10s")
            await safe_edit_message(query,
                "⚠️ **BẠN ĐANG THUÊ QUÁ NHANH**\n\nVui lòng chờ 10 giây giữa các lần thuê."
            )
            return
        
        # ===== LỚP BẢO VỆ 1: KIỂM TRA SỐ DƯ LẦN 1 =====
        if db_user.balance < final_price:
            shortage = final_price - db_user.balance
            keyboard = [
                [InlineKeyboardButton("💳 NẠP TIỀN NGAY", callback_data="menu_deposit")],
                [InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await safe_edit_message(query,
                f"❌ **SỐ DƯ KHÔNG ĐỦ!**\n\n"
                f"• **Cần:** {final_price:,}đ\n"
                f"• **Có:** {db_user.balance:,}đ\n"
                f"• **Thiếu:** {shortage:,}đ\n\n"
                f"Vui lòng nạp thêm tiền để tiếp tục.",
                reply_markup
            )
            return
        
        # Xóa menu hiện tại (có bắt lỗi)
        await safe_delete_message(query.message)
        
        loading_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⏳ **ĐANG XỬ LÝ YÊU CẦU...**\n\n🤖 Vui lòng chờ trong giây lát.",
            parse_mode='Markdown'
        )
        
        try:
            # ===== GỌI API LẤY SỐ (TRƯỚC KHI TRỪ TIỀN) =====
            url = f"{BASE_URL}/sim/get_sim"
            params = {
                'api_key': API_KEY,
                'service_id': service_id
            }
            if network_id and network_id != 'None':
                params['network_id'] = network_id
            
            logger.info(f"📞 Gọi API lấy số: service_id={service_id}, network_id={network_id}")
            response = requests.get(url, params=params, timeout=15)
            
            # ===== KIỂM TRA HTTP STATUS =====
            if response.status_code == 401:
                logger.error("🔴 API_KEY hết hạn")
                await loading_msg.edit_text("❌ **LỖI XÁC THỰC API**\n\nVui lòng liên hệ admin.")
                return
            
            response_data = response.json()
            logger.info(f"API response: {response_data}")
            
            # ===== XỬ LÝ KHI API THÀNH CÔNG =====
            if response_data.get('status') == 200:
                sim_data = response_data.get('data', {})
                phone = sim_data.get('phone')
                otp_id = sim_data.get('otpId')
                sim_id = sim_data.get('simId')
                actual_price = sim_data.get('payment', final_price - 1000)
                
                # ===== KIỂM TRA SỐ TRÙNG =====
                existing_rental = Rental.query.filter_by(
                    phone_number=phone, 
                    status='waiting'
                ).first()
                
                if existing_rental:
                    logger.error(f"⚠️ Số {phone} đã được thuê bởi user {existing_rental.user_id}")
                    await loading_msg.edit_text(
                        "❌ **LỖI HỆ THỐNG**\n\nSố này đã được cấp cho người khác.\nVui lòng thử lại sau.",
                        parse_mode='Markdown'
                    )
                    return
                
                # ===== BẮT ĐẦU TRANSACTION =====
                try:
                    # Refresh user để lấy số dư mới nhất
                    db.session.refresh(db_user)
                    
                    # ===== XÓA CACHE VÀ KIỂM TRA LẠI SỐ DƯ =====
                    db.session.expire_all()
                    db.session.refresh(db_user)
                    logger.info(f"💰 SỐ DƯ THỰC TẾ SAU KHI REFRESH: {db_user.balance}đ")
                    
                    # ===== LỚP BẢO VỆ 2: KIỂM TRA LẠI SỐ DƯ SAU REFRESH =====
                    if db_user.balance < final_price:
                        logger.error(f"❌ Phát hiện bất thường: Số dư {db_user.balance}đ không đủ sau refresh")
                        await loading_msg.edit_text(
                            "❌ **LỖI HỆ THỐNG**\n\nSố dư không đủ, vui lòng thử lại.",
                            parse_mode='Markdown'
                        )
                        return
                    
                    old_balance = db_user.balance
                    logger.info(f"💰 [TRƯỚC KHI TRỪ] Số dư: {old_balance}đ (đã kiểm tra lần cuối)")
                    
                    # Lấy thông tin dịch vụ
                    rent_info = context.user_data.get('rent', {})
                    if not rent_info:
                        logger.error("❌ user_data mất")
                        await loading_msg.edit_text(
                            "❌ **LỖI SESSION**\n\nVui lòng chọn lại từ đầu.",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("📱 CHỌN LẠI", callback_data="menu_rent")
                            ]])
                        )
                        return
                    
                    # Tạo rental object
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
                        expires_at=datetime.now() + timedelta(minutes=5)
                    )
                    db.session.add(rental)
                    
                    # ===== TRỪ TIỀN =====
                    db_user.balance -= final_price
                    db_user.total_spent += final_price
                    db_user.total_rentals += 1
                    db_user.updated_at = datetime.now()
                    
                    # ===== LỚP BẢO VỆ 3: DELAY NHỎ GIỮA CÁC TRANSACTION =====
                    await asyncio.sleep(0.3)
                    
                    # ===== COMMIT MỘT LẦN DUY NHẤT =====
                    db.session.commit()
                    
                    # ===== KIỂM TRA SAU COMMIT =====
                    db.session.refresh(db_user)
                    logger.info(f"✅ User {user.id} thuê số {phone} thành công")
                    logger.info(f"💰 Đã trừ {final_price}đ (từ {old_balance}đ còn {db_user.balance}đ)")
                    logger.info(f"🔍 [SAU COMMIT] User {user.id} - Số dư: {db_user.balance}đ")
                    
                    # ===== KIỂM TRA SỐ DƯ KỲ VỌNG =====
                    expected_balance = old_balance - final_price
                    if db_user.balance != expected_balance:
                        logger.error(f"❌ LỖI NGHIÊM TRỌNG: Số dư không khớp! expected={expected_balance}, actual={db_user.balance}")
                    
                    # Xóa dữ liệu tạm
                    if 'rent' in context.user_data:
                        del context.user_data['rent']
                    
                    # Lưu rental vào context
                    if 'active_rentals' not in context.user_data:
                        context.user_data['active_rentals'] = []
                    context.user_data['active_rentals'].append({
                        'id': rental.id,
                        'phone': phone,
                        'service': rent_info['service_name'],
                        'expires_at': rental.expires_at.isoformat()
                    })
                    
                    # Tạo keyboard
                    keyboard = [
                        [InlineKeyboardButton(f"📞 {phone} - {rent_info['service_name']}", callback_data=f"rent_view_{rental.id}")],
                        [InlineKeyboardButton("📋 DANH SÁCH SỐ", callback_data="menu_rent_list")],
                        [InlineKeyboardButton("🆕 THUÊ SỐ KHÁC", callback_data="menu_rent")],
                        [InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    text = (
                        f"✅ **THUÊ SỐ THÀNH CÔNG!**\n\n"
                        f"📞 **Số:** `{phone}`\n"
                        f"📱 **Dịch vụ:** {rent_info['service_name']}\n"
                        f"💰 **Đã thanh toán:** {final_price:,}đ\n"
                        f"💵 **Số dư còn lại:** {db_user.balance:,}đ\n"
                        f"⏰ **Hết hạn lúc:** {rental.expires_at.strftime('%H:%M:%S')}\n\n"
                        f"🤖 **TỰ ĐỘNG KIỂM TRA OTP**\n"
                        f"• Bot sẽ tự động kiểm tra và báo khi có OTP\n"
                        f"• Bạn có thể theo dõi số qua menu trên"
                    )
                    
                    await loading_msg.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')
                    
                    # Tạo task auto-check
                    task = asyncio.create_task(
                        auto_check_otp_task(
                            context.bot,
                            chat_id=update.effective_chat.id,
                            otp_id=otp_id,
                            rental_id=rental.id,
                            user_id=user.id,
                            service_name=rent_info['service_name'],
                            phone=phone
                        )
                    )
                    auto_check_tasks[rental.id] = task
                    
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"❌ Lỗi database: {e}")
                    await loading_msg.edit_text(
                        "❌ **LỖI HỆ THỐNG**\n\nKhông thể lưu giao dịch.\nVui lòng thử lại sau.",
                        parse_mode='Markdown'
                    )
            
            # ===== XỬ LÝ KHI API LỖI =====
            else:
                error_msg = response_data.get('message', 'Không rõ lỗi')
                logger.info(f"🔍 API lỗi: {error_msg}")
                
                # Kiểm tra lỗi hết số
                if any(word in error_msg.lower() for word in ['hết số', 'no sim', 'out of stock', 'hết sim']):
                    display_msg = "⚠️ **DỊCH VỤ ĐANG TẠM HẾT SỐ**\n\n" \
                                f"📢 {error_msg}\n\n" \
                                "💡 **Gợi ý:**\n" \
                                "• Chọn nhà mạng khác\n" \
                                "• Thử lại sau 5-10 phút\n" \
                                "• Chọn dịch vụ khác"
                    
                    # Lấy thông tin dịch vụ hiện tại
                    rent_info = context.user_data.get('rent', {})
                    current_service_id = rent_info.get('service_id')
                    
                    # Tạo menu dịch vụ khác
                    keyboard = []
                    services = await get_services()
                    
                    if services:
                        other_services = [sv for sv in services if str(sv['id']) != current_service_id][:6]
                        
                        row = []
                        for sv in other_services:
                            try:
                                original_price = int(float(sv['price']))
                            except:
                                original_price = 1200
                            
                            button = InlineKeyboardButton(
                                f"📱 {sv['name']}",
                                callback_data=f"rent_service_{sv['id']}_{sv['name']}_{original_price}"
                            )
                            row.append(button)
                            
                            if len(row) == 2:
                                keyboard.append(row)
                                row = []
                        
                        if row:
                            keyboard.append(row)
                    
                    keyboard.append([InlineKeyboardButton("🔄 THỬ LẠI", callback_data="menu_rent")])
                    keyboard.append([InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                else:
                    display_msg = f"❌ **LỖI TỪ MÁY CHỦ**\n\n📢 {error_msg}"
                    keyboard = [[InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                
                await loading_msg.edit_text(
                    display_msg,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
        except requests.exceptions.Timeout:
            await loading_msg.edit_text(
                "⏰ **TIMEOUT - MÁY CHỦ KHÔNG PHẢN HỒI**\n\n"
                "Vui lòng thử lại sau.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"❌ Lỗi thuê số: {e}")
            import traceback
            traceback.print_exc()
            await loading_msg.edit_text(
                "❌ **LỖI KẾT NỐI**\n\n"
                "Vui lòng thử lại sau.",
                parse_mode='Markdown'
            )

async def rent_check_callback(update: Update, context: Context):
    """Kiểm tra OTP thủ công - GỬI CẢ TEXT VÀ AUDIO"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    try:
        data = query.data.split('_')
        otp_id = data[2]
        rental_id = int(data[3])
    except Exception as e:
        logger.error(f"Lỗi parse check: {e}")
        await query.edit_message_text("❌ **LỖI DỮ LIỆU**\n\nVui lòng thử lại.")
        return
    
    # Hiển thị trạng thái đang kiểm tra
    await query.edit_message_text(
        "⏳ **ĐANG KIỂM TRA OTP...**\n\nVui lòng chờ trong giây lát.",
        parse_mode='Markdown'
    )
    
    try:
        # Gọi API kiểm tra OTP
        url = f"{BASE_URL}/otp/get_otp_by_phone_api_key"
        params = {
            'api_key': API_KEY,
            'otp_id': otp_id
        }
        
        logger.info(f"🔍 Kiểm tra OTP cho otp_id={otp_id}")
        response = requests.get(url, params=params, timeout=10)
        response_data = response.json()
        
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
                content = otp_data.get('content', '')
                sender = otp_data.get('senderName', '')
                audio_url = otp_data.get('audio')
                
                rental.status = 'success'
                rental.otp_code = otp_code or "Audio OTP"
                rental.content = content
                rental.updated_at = datetime.now()
                db.session.commit()
                
                # ==== GỬI OTP DẠNG SỐ (NẾU CÓ) ====
                if otp_code:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"✅ **MÃ OTP:** `{otp_code}`\n📝 {content}",
                        parse_mode='Markdown'
                    )
                    logger.info(f"✅ Đã gửi OTP text cho rental {rental_id}")
                
                # ==== GỬI FILE AUDIO (NẾU CÓ) ====
                if audio_url:
                    try:
                        # Thông báo đang tải audio
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="⏳ **ĐANG TẢI FILE AUDIO OTP...**",
                            parse_mode='Markdown'
                        )
                        
                        # Tải file audio
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        audio_response = requests.get(audio_url, headers=headers, timeout=30)
                        
                        if audio_response.status_code == 200:
                            # Gửi file audio
                            await context.bot.send_audio(
                                chat_id=update.effective_chat.id,
                                audio=audio_response.content,
                                filename=f"otp_audio_{rental_id}.mp3",
                                title=f"OTP Audio - {rental.service_name}",
                                caption=f"📱 **{rental.service_name}**\n📞 `{rental.phone_number}`",
                                parse_mode='Markdown'
                            )
                            logger.info(f"✅ Đã gửi audio OTP cho rental {rental_id}")
                        else:
                            # Nếu lỗi, gửi link
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=f"🔊 **LINK AUDIO OTP**\n\n"
                                    f"📱 **{rental.service_name}**\n"
                                    f"📞 `{rental.phone_number}`\n\n"
                                    f"[Nhấn vào đây để nghe]({audio_url})",
                                parse_mode='Markdown'
                            )
                    except Exception as e:
                        logger.error(f"Lỗi tải audio: {e}")
                        # Gửi link dự phòng
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"🔊 **LINK AUDIO OTP**\n\n"
                                f"📱 **{rental.service_name}**\n"
                                f"📞 `{rental.phone_number}`\n\n"
                                f"[Nhấn vào đây để nghe]({audio_url})",
                            parse_mode='Markdown'
                        )
                
                # Nếu không có cả OTP và audio
                elif not otp_code and not audio_url:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"✅ **ĐÃ NHẬN OTP**\n\n📱 **Dịch vụ:** {rental.service_name}\n📞 **Số:** `{rental.phone_number}`",
                        parse_mode='Markdown'
                    )
                
                await query.delete_message()
                
            elif status == 202:
                expires_in = int((rental.expires_at - datetime.now()).total_seconds() / 60)
                await query.edit_message_text(
                    f"⏳ **CHƯA CÓ OTP**\n\n• Còn {expires_in} phút",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("⏳ **ĐANG CHỜ OTP...**")
                
    except Exception as e:
        logger.error(f"Lỗi kiểm tra OTP: {e}")
        await query.edit_message_text("❌ **LỖI KẾT NỐI**")

async def auto_check_otp_task(bot, chat_id: int, otp_id: str, rental_id: int, user_id: int, service_name: str, phone: str):
    """Tự động kiểm tra OTP - SIÊU BẢO VỆ + GỬI CẢ TEXT VÀ AUDIO + CHỐNG CỘNG TRỪ SAI"""
    logger.info(f"🤖 Bắt đầu auto-check OTP cho rental {rental_id}")
    
    max_checks = 120
    check_count = 0
    
    # Cache để tránh xử lý trùng
    processed = False
    
    try:
        while check_count < max_checks and not processed:
        # === KIỂM TRA THỜI GIAN HẾT HẠN ===
            with app.app_context():
                rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                if rental and rental.status == 'waiting' and not rental.refunded:
                    now = datetime.now()
                    if now > rental.expires_at:
                        logger.info(f"⏰ Rental {rental_id} đã hết hạn (timeout), tiến hành hoàn tiền")
                        
                        refund = rental.price_charged
                        user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()
                        if user:
                            old_balance = user.balance
                            user.balance += refund
                            rental.status = 'expired'
                            rental.refunded = True
                            rental.refund_amount = refund
                            rental.refunded_at = now
                            db.session.commit()
                            
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                    f"📞 Số `{phone}` đã hết hạn.\n"
                                    f"💰 **Đã tự động hoàn lại {refund:,}đ!**\n"
                                    f"💵 **Số dư mới:** {user.balance:,}đ",
                                parse_mode='Markdown'
                            )
                            
                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]
                            return
            if asyncio.current_task().cancelled():
                logger.info(f"🛑 Task {rental_id} bị hủy")
                return
                
            check_count += 1
            logger.info(f"🔄 Auto-check OTP lần {check_count}/{max_checks} cho rental {rental_id}")
            
            try:
                with app.app_context():
                    # ===== LỚP BẢO VỆ 1: KIỂM TRA RENTAL VỚI KHÓA =====
                    rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                    
                    if not rental:
                        logger.info(f"❌ Rental {rental_id} không tồn tại")
                        return
                    
                    # ===== LỚP BẢO VỆ 2: NẾU ĐÃ HOÀN THÌ DỪNG =====
                    if rental.refunded:
                        logger.info(f"✅ Rental {rental_id} đã hoàn {rental.refund_amount}đ, dừng auto-check")
                        return
                    
                    # ===== LỚP BẢO VỆ 3: NẾU ĐÃ XỬ LÝ XONG THÌ DỪNG =====
                    if rental.status in ['cancelled', 'expired', 'success']:
                        logger.info(f"✅ Rental {rental_id} đã {rental.status}, dừng auto-check")
                        return
                
                # Gọi API kiểm tra OTP
                url = f"{BASE_URL}/otp/get_otp_by_phone_api_key"
                params = {'api_key': API_KEY, 'otp_id': otp_id}
                response = requests.get(url, params=params, timeout=5)
                response_data = response.json()
                
                status = response_data.get('status')
                
                # ===== XỬ LÝ KHI CÓ OTP =====
                if status == 200:
                    otp_data = response_data.get('data', {})
                    otp_code = otp_data.get('code')
                    content = otp_data.get('content', '')
                    audio_url = otp_data.get('audio')
                    
                    with app.app_context():
                        # ===== LỚP BẢO VỆ 4: KIỂM TRA LẠI TRƯỚC KHI CẬP NHẬT =====
                        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                        
                        if rental and rental.status == 'waiting' and not rental.refunded:
                            rental.status = 'success'
                            rental.otp_code = otp_code or "Audio OTP"
                            rental.content = content
                            rental.updated_at = datetime.now()
                            db.session.commit()
                            processed = True
                            
                            # ==== GỬI MÃ OTP DẠNG SỐ (NẾU CÓ) ====
                            if otp_code:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"🔑 **MÃ OTP:** `{otp_code}`\n📝 {content}\n📱 **Dịch vụ:** {service_name}\n📞 **Số:** `{phone}`",
                                    parse_mode='Markdown'
                                )
                                logger.info(f"✅ Đã gửi OTP text cho rental {rental_id}")
                            
                            # ==== GỬI FILE AUDIO (NẾU CÓ) ====
                            if audio_url:
                                try:
                                    # Thông báo đang tải audio
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text="⏳ **ĐANG TẢI FILE AUDIO OTP...**",
                                        parse_mode='Markdown'
                                    )
                                    
                                    # Tải file audio
                                    headers = {'User-Agent': 'Mozilla/5.0'}
                                    audio_response = requests.get(audio_url, headers=headers, timeout=30)
                                    
                                    if audio_response.status_code == 200:
                                        # Gửi file audio
                                        await bot.send_audio(
                                            chat_id=chat_id,
                                            audio=audio_response.content,
                                            filename=f"otp_audio_{rental_id}.mp3",
                                            title=f"OTP Audio - {service_name}",
                                            caption=f"📱 **{service_name}**\n📞 `{phone}`",
                                            parse_mode='Markdown'
                                        )
                                        logger.info(f"✅ Đã gửi audio OTP cho rental {rental_id}")
                                    else:
                                        # Nếu lỗi, gửi link
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=f"🔊 **LINK AUDIO OTP**\n\n"
                                                f"📱 **{service_name}**\n"
                                                f"📞 `{phone}`\n\n"
                                                f"[Nhấn vào đây để nghe]({audio_url})",
                                            parse_mode='Markdown'
                                        )
                                except Exception as e:
                                    logger.error(f"Lỗi tải audio: {e}")
                                    # Gửi link dự phòng
                                    await bot.send_message(
                                        chat_id=chat_id,
                                        text=f"🔊 **LINK AUDIO OTP**\n\n"
                                            f"📱 **{service_name}**\n"
                                            f"📞 `{phone}`\n\n"
                                            f"[Nhấn vào đây để nghe]({audio_url})",
                                        parse_mode='Markdown'
                                    )
                            
                            # Nếu không có cả OTP và audio
                            elif not otp_code and not audio_url:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"✅ **ĐÃ NHẬN OTP**\n\n📱 **Dịch vụ:** {service_name}\n📞 **Số:** `{phone}`",
                                    parse_mode='Markdown'
                                )
                            
                            # Xóa task khỏi dictionary
                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]
                            return
                
                # ===== XỬ LÝ KHI CHƯA CÓ OTP =====
                elif status in [202, 312]:
                    # Chưa có OTP, tiếp tục chờ
                    pass
                
                # ===== XỬ LÝ KHI HẾT HẠN (AUTO HOÀN TIỀN) =====
                elif status == 400:
                    with app.app_context():
                        # ===== LỚP BẢO VỆ 5: KIỂM TRA KỸ TRƯỚC KHI AUTO-HOÀN =====
                        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                        
                        if not rental:
                            logger.info(f"❌ Rental {rental_id} không tồn tại")
                            return
                        
                        if rental.status != 'waiting':
                            logger.info(f"✅ Rental {rental_id} không còn ở trạng thái waiting, bỏ qua")
                            return
                        
                        if rental.refunded:
                            logger.info(f"✅ Rental {rental_id} đã được hoàn {rental.refund_amount}đ, bỏ qua")
                            return
                        
                        # ===== QUAN TRỌNG: CHỈ HOÀN ĐÚNG price_charged =====
                        refund = rental.price_charged  # DÒNG NÀY QUYẾT ĐỊNH - KHÔNG DÙNG cost
                        
                        logger.info(f"💰 AUTO-HOÀN: rental {rental_id}")
                        logger.info(f"   price_charged: {rental.price_charged}đ")
                        logger.info(f"   cost: {rental.cost}đ")
                        logger.info(f"   Số tiền sẽ hoàn: {refund}đ")
                        
                        # ===== KIỂM TRA XEM CÓ HOÀN GẦN ĐÂY KHÔNG =====
                        recent_refund = Rental.query.filter(
                            Rental.user_id == rental.user_id,
                            Rental.refunded == True,
                            Rental.refunded_at > datetime.now() - timedelta(seconds=10)
                        ).first()
                        
                        if recent_refund:
                            logger.warning(f"⚠️ Phát hiện hoàn tiền gần đây (cách {datetime.now() - recent_refund.refunded_at}), bỏ qua auto-hoàn")
                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]
                            return
                        
                        # ===== LẤY USER VỚI KHÓA =====
                        user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()
                        
                        if not user:
                            logger.error(f"❌ Không tìm thấy user {rental.user_id}")
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                    f"📞 Số `{phone}` đã hết hạn.\n"
                                    f"❌ Không tìm thấy user để hoàn tiền!",
                                parse_mode='Markdown'
                            )
                            rental.status = 'expired'
                            rental.updated_at = datetime.now()
                            db.session.commit()
                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]
                            return
                        
                        # ===== LƯU SỐ DƯ CŨ =====
                        old_balance = user.balance
                        
                        # ===== KIỂM TRA CHÉO SỐ DƯ KỲ VỌNG =====
                        expected_balance = user.balance + refund
                        
                        logger.info(f"   Số dư hiện tại: {user.balance}đ")
                        logger.info(f"   Số dư kỳ vọng: {expected_balance}đ")
                        
                        # ===== THỰC HIỆN HOÀN TIỀN =====
                        user.balance += refund
                        rental.refunded = True
                        rental.refund_amount = refund
                        rental.refunded_at = datetime.now()
                        
                        # ===== KIỂM TRA SAU KHI CẬP NHẬT =====
                        if user.balance == expected_balance:
                            logger.info(f"✅ AUTO-HOÀN THÀNH CÔNG: {old_balance}đ → {user.balance}đ (+{refund}đ)")
                            
                            # Commit thay đổi
                            rental.status = 'expired'
                            rental.updated_at = datetime.now()
                            db.session.commit()
                            
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                    f"📞 Số `{phone}` đã hết hạn.\n"
                                    f"💰 **Đã tự động hoàn lại {refund:,}đ vào tài khoản!**\n"
                                    f"💵 **Số dư mới:** {user.balance:,}đ",
                                parse_mode='Markdown'
                            )
                            
                            # Xóa task
                            if rental_id in auto_check_tasks:
                                del auto_check_tasks[rental_id]
                            return
                        else:
                            logger.error(f"❌ AUTO-HOÀN SAI: {old_balance} + {refund} = {user.balance} (phải là {expected_balance})")
                            db.session.rollback()
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                    f"📞 Số `{phone}` đã hết hạn.\n"
                                    f"❌ **Lỗi hệ thống, vui lòng liên hệ admin!**",
                                parse_mode='Markdown'
                            )
                            return
                            
            except Exception as e:
                logger.error(f"Lỗi auto-check: {e}")
                import traceback
                traceback.print_exc()
            
            # ===== CHỜ 5 GIÂY TRƯỚC LẦN KIỂM TRA TIẾP THEO =====
            await asyncio.sleep(5)
        
        # ===== HẾT 120 LẦN CHECK (10 PHÚT) =====
        if not processed:
            with app.app_context():
                # Lấy rental với khóa để hoàn tiền
                rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
                
                if rental and rental.status == 'waiting' and not rental.refunded:
                    user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()
                    
                    if user:
                        refund = rental.price_charged  # DÙNG price_charged, KHÔNG dùng cost
                        old_balance = user.balance
                        
                        # HOÀN TIỀN NGAY LẬP TỨC
                        user.balance += refund
                        rental.status = 'expired'
                        rental.refunded = True
                        rental.refund_amount = refund
                        rental.refunded_at = datetime.now()
                        
                        db.session.commit()
                        
                        logger.info(f"💰 AUTO HOÀN SAU KHI HẾT CHECK: rental {rental_id}")
                        logger.info(f"   {old_balance}đ → {user.balance}đ (+{refund}đ)")
                        
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                f"📞 Số `{phone}` đã hết thời gian chờ OTP.\n"
                                f"💰 **ĐÃ TỰ ĐỘNG HOÀN LẠI {refund:,}Đ!**\n"
                                f"💵 **Số dư mới:** {user.balance:,}đ",
                            parse_mode='Markdown'
                        )
                    else:
                        # Không tìm thấy user - vẫn thông báo nhưng không hoàn được
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⏰ **SỐ ĐÃ HẾT HẠN**\n\n"
                                f"📞 Số `{phone}` đã hết thời gian chờ OTP.\n"
                                f"❌ **LỖI: Không tìm thấy user để hoàn tiền!**",
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
    except:
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
        
        expires_in = int((rental.expires_at - datetime.now()).total_seconds() / 60)
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
                keyboard.append([InlineKeyboardButton("🔍 KIỂM TRA OTP", callback_data=f"rent_check_{rental.otp_id}_{rental.id}")])
            if rental.sim_id:
                keyboard.append([InlineKeyboardButton("❌ HỦY SỐ", callback_data=f"rent_cancel_{rental.sim_id}_{rental.id}")])
        elif rental.status == 'success':
            keyboard.append([InlineKeyboardButton(
                "🔄 THUÊ LẠI SỐ NÀY", 
                callback_data=f"rent_reuse_{rental.phone_number}_{rental.service_id}"
            )])
        
        if rental.otp_code:
            text += f"🔑 **MÃ OTP:** `{rental.otp_code}`\n"
            if rental.content:
                text += f"📝 **Nội dung:** {rental.content}\n"
        
        keyboard.append([InlineKeyboardButton("📋 DANH SÁCH SỐ", callback_data="menu_rent_list")])
        keyboard.append([InlineKeyboardButton("🔙 QUAY LẠI", callback_data="menu_rent")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

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
            response = requests.get(url, params=params, timeout=15)
            response_data = response.json()
            
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
                for sv in services:
                    if str(sv['id']) == service_id:
                        service_name = sv['name']
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
                    created_at=datetime.now(),
                    expires_at=datetime.now() + timedelta(minutes=5)
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
                    f"💰 **Đã thanh toán:** {price}đ\n"
                    f"💵 **Số dư còn lại:** {db_user.balance}đ",
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
    """Hủy số - SIÊU BẢO VỆ CHỐNG CỘNG SAI (ĐÃ CẬP NHẬT)"""
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
    
    # ===== LỚP BẢO VỆ 1: KIỂM TRA XEM CÓ ĐANG BỊ AUTO-CHECK XỬ LÝ KHÔNG =====
    if rental_id in auto_check_tasks:
        logger.info(f"⏳ Đang có task auto-check cho rental {rental_id}, chờ 0.5s")
        await asyncio.sleep(0.5)
        # Kiểm tra lại sau khi chờ
        if rental_id not in auto_check_tasks:
            logger.info(f"✅ Task auto-check đã kết thúc, tiếp tục xử lý hủy")
    
    # ===== LỚP BẢO VỆ 2: KHÓA CẤP ĐỘ RENTAL =====
    with app.app_context():
        # Lấy rental với khóa, đồng thời lấy user
        rental = Rental.query.filter_by(id=rental_id).with_for_update().first()
        
        if not rental:
            await query.edit_message_text("❌ **KHÔNG TÌM THẤY GIAO DỊCH**")
            return
        
        user = User.query.filter_by(user_id=rental.user_id).with_for_update().first()
        
        # ===== LỚP BẢO VỆ 3: KIỂM TRA TRẠNG THÁI HOÀN TIỀN =====
        if rental.refunded:
            logger.warning(f"⚠️ CỐ GẮNG HỦY SỐ ĐÃ HOÀN: {rental_id}")
            await query.edit_message_text(
                f"❌ **SỐ NÀY ĐÃ ĐƯỢC HOÀN {rental.refund_amount}đ**\n\n"
                f"📞 {rental.phone_number}\n"
                f"⏰ Hoàn lúc: {rental.refunded_at.strftime('%H:%M:%S') if rental.refunded_at else 'N/A'}\n\n"
                f"✅ Mỗi số chỉ được hoàn 1 lần!",
                parse_mode='Markdown'
            )
            return
        
        # ===== LỚP BẢO VỆ 4: KIỂM TRA SỐ DƯ HIỆN TẠI =====
        expected_balance = user.balance + rental.price_charged
        logger.info(f"💰 KIỂM TRA CHÉO:")
        logger.info(f"   Số dư hiện tại: {user.balance}đ")
        logger.info(f"   Tiền hoàn: +{rental.price_charged}đ")
        logger.info(f"   Số dư sau hoàn: {expected_balance}đ")
        
        # ===== LỚP BẢO VỆ 5: KIỂM TRA RENTAL STATUS =====
        if rental.status == 'success':
            await query.edit_message_text("❌ **ĐÃ NHẬN OTP**\n\nKhông thể hủy.")
            return
        
        # ===== LỚP BẢO VỆ 6: HỦY TASK AUTO-CHECK =====
        if rental_id in auto_check_tasks:
            try:
                auto_check_tasks[rental_id].cancel()
                logger.info(f"🛑 Đã hủy task auto-check cho rental {rental_id}")
                await asyncio.sleep(0.5)
                auto_check_tasks.pop(rental_id, None)
            except Exception as e:
                logger.error(f"Lỗi hủy task: {e}")
        
        # ===== LỚP BẢO VỆ 7: GỌI API HỦY SỐ =====
        try:
            url = f"{BASE_URL}/sim/cancel_api_key/{sim_id}?api_key={API_KEY}"
            response = requests.get(url, timeout=10)
            api_data = response.json()
            api_success = api_data.get('status') == 200
            
            # ===== LỚP BẢO VỆ 8: KIỂM TRA LẠI LẦN CUỐI TRƯỚC KHI HOÀN =====
            # Refresh user để lấy số dư mới nhất
            db.session.expire_all()
            db.session.refresh(user)
            
            # Kiểm tra một lần nữa xem đã hoàn chưa (tránh race condition)
            if rental.refunded:
                logger.error(f"❌ PHÁT HIỆN RACE CONDITION: rental {rental_id} đã được hoàn")
                db.session.rollback()
                await query.edit_message_text("❌ Giao dịch đã được xử lý trước đó")
                return
            
            old_balance = user.balance
            refund_amount = rental.price_charged
            
            # ===== LỚP BẢO VỆ 9: CẬP NHẬT VỚI CHECK =====
            # Chỉ cập nhật nếu số dư hiện tại + tiền hoàn = số dư kỳ vọng
            if user.balance + refund_amount != expected_balance:
                logger.error(f"❌ PHÁT HIỆN BẤT THƯỜNG:")
                logger.error(f"   user.balance ({user.balance}) + refund ({refund_amount}) = {user.balance + refund_amount}")
                logger.error(f"   expected_balance = {expected_balance}")
                await query.edit_message_text("❌ LỖI HỆ THỐNG: Phát hiện bất thường số dư")
                return
            
            # Cập nhật
            rental.status = 'cancelled'
            rental.refunded = True
            rental.refund_amount = refund_amount
            rental.refunded_at = datetime.now()
            
            user.balance += refund_amount
            
            # ===== LỚP BẢO VỆ 10: LOG CHI TIẾT =====
            logger.info(f"✅ HOÀN TIỀN THÀNH CÔNG!")
            logger.info(f"   User: {user.user_id}")
            logger.info(f"   Rental: {rental_id}")
            logger.info(f"   Số dư cũ: {old_balance}")
            logger.info(f"   Tiền hoàn: +{refund_amount}")
            logger.info(f"   Số dư mới: {user.balance}")
            logger.info(f"   Expected: {expected_balance}")
            logger.info(f"   Status: {'MATCH' if user.balance == expected_balance else 'MISMATCH'}")
            
            db.session.commit()
            
            # ===== LỚP BẢO VỆ 11: KIỂM TRA SAU COMMIT =====
            db.session.refresh(user)
            db.session.refresh(rental)
            
            if not rental.refunded or rental.refund_amount != refund_amount:
                logger.error(f"❌ LỖI NGHIÊM TRỌNG: Dữ liệu không nhất quán sau commit")
            
            # Gửi thông báo
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
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ LỖI: {e}")
            await query.edit_message_text(f"❌ **LỖI**\n\n{str(e)}")

async def rent_list_callback(update: Update, context: Context):
    """Hiển thị danh sách số đang thuê - CÓ NÚT HỦY CHO SỐ CHỜ OTP"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user = update.effective_user
    
    with app.app_context():
        # ===== SỬA QUAN TRỌNG: Lấy tất cả số 'waiting' không quan tâm hết hạn =====
        waiting_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status == 'waiting'  # Chỉ cần status waiting, không check expires_at
        ).order_by(Rental.created_at.desc()).all()
        
        recent_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status == 'success'
        ).order_by(Rental.created_at.desc()).limit(10).all()
        
        old_rentals = Rental.query.filter(
            Rental.user_id == user.id,
            Rental.status.in_(['cancelled', 'expired'])
        ).order_by(Rental.created_at.desc()).limit(5).all()
    
    if query.message:
        try:
            await query.message.delete()
        except:
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
    
    # ===== HIỂN THỊ SỐ ĐANG CHỜ OTP (kể cả hết hạn) =====
    if waiting_rentals:
        text += "🟢 **ĐANG CHỜ OTP:**\n"
        for rental in waiting_rentals:
            # Tính thời gian còn lại
            expires_in = int((rental.expires_at - datetime.now()).total_seconds() / 60)
            if expires_in < 0:
                time_display = "Chờ OTP"
            else:
                time_display = f"⏳ Còn {expires_in} phút"
            
            text += f"• `{rental.phone_number}` - {rental.service_name} ({time_display})\n"
            
            # ===== THÊM NÚT HỦY CHO MỖI SỐ =====
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
    
    # ===== HIỂN THỊ SỐ ĐÃ NHẬN OTP =====
    if recent_rentals:
        text += "✅ **ĐÃ NHẬN OTP GẦN ĐÂY:**\n"
        for rental in recent_rentals:
            otp_display = rental.otp_code or "Audio OTP"
            text += f"• `{rental.phone_number}` - {rental.service_name} - OTP: {otp_display}\n"
            
            # Nút thuê lại
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 THUÊ LẠI {rental.phone_number}",
                    callback_data=f"rent_reuse_{rental.phone_number}_{rental.service_id}"
                )
            ])
        text += "\n"
    
    # ===== HIỂN THỊ SỐ ĐÃ HẾT HẠN/HỦY =====
    if old_rentals:
        text += "⏰ **ĐÃ HẾT HẠN/HỦY:**\n"
        for rental in old_rentals:
            status_icon = "❌" if rental.status == 'cancelled' else "⏰"
            text += f"• {status_icon} `{rental.phone_number}` - {rental.service_name}\n"
    
    # Nút điều hướng
    keyboard.append([InlineKeyboardButton("🆕 THUÊ SỐ MỚI", callback_data="menu_rent")])
    keyboard.append([InlineKeyboardButton("🔙 MENU CHÍNH", callback_data="menu_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )