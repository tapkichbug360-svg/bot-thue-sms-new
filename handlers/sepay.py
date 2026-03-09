from flask import request, jsonify
import logging
from bot import app
from database.models import User, Transaction, db
from datetime import datetime, timedelta, timezone
import os
import re
import asyncio
import hashlib
from telegram import Bot

logger = logging.getLogger(__name__)

MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Múi giờ Việt Nam (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

telegram_bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

def get_vn_time():
    """Lấy thời gian Việt Nam hiện tại"""
    return datetime.now(VN_TZ).replace(tzinfo=None)

async def send_telegram_notification(chat_id, message):
    try:
        if telegram_bot:
            await telegram_bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown'
            )
            logger.info(f"✅ Đã gửi thông báo Telegram cho user {chat_id}")
    except Exception as e:
        logger.error(f"❌ Lỗi gửi Telegram: {e}")

def setup_sepay_webhook(app):
    @app.route('/webhook/sepay', methods=['POST'])
    def sepay_webhook():
        try:
            data = request.json
            logger.info("="*60)
            logger.info("📩 NHẬN WEBHOOK TỪ SEPAY")
            logger.info(f"Dữ liệu: {data}")
            
            transfer_type = data.get('transferType')
            account_number = data.get('accountNumber')
            amount = int(float(data.get('transferAmount', 0)))
            content = data.get('content', '').strip()
            transaction_id = data.get('transactionId', '')
            
            if transfer_type != 'in':
                return jsonify({"success": True, "message": "Ignored"}), 200
            
            if account_number != MB_ACCOUNT:
                return jsonify({"success": True, "message": "Wrong account"}), 200
            
            # Tìm mã NAP
            match = re.search(r'NAP\s*([A-Z0-9]{8})', content.upper())
            if not match:
                return jsonify({"success": True, "message": "No NAP code found"}), 200
            
            transaction_code = match.group(1)
            logger.info(f"🔍 Mã NAP: {transaction_code}")
            
            with app.app_context():
                # ===== KIỂM TRA GIAO DỊCH ĐÃ TỒN TẠI =====
                existing = Transaction.query.filter_by(
                    transaction_code=transaction_code
                ).first()
                
                if existing and existing.status == 'success':
                    logger.warning(f"⚠️ Giao dịch {transaction_code} đã được xử lý trước đó")
                    return jsonify({
                        "success": True, 
                        "message": "Already processed"
                    }), 200
                
                # ===== XÁC ĐỊNH USER =====
                target_user = None
                
                # Cách 1: Từ giao dịch pending
                if existing and existing.status == 'pending':
                    target_user = User.query.get(existing.user_id)
                    logger.info(f"✅ Tìm thấy user từ giao dịch pending: {target_user.user_id if target_user else 'None'}")
                
                # Cách 2: Tìm user_id trong nội dung
                if not target_user:
                    user_match = re.search(r'tu (\d+)', content)
                    if user_match:
                        found_user_id = int(user_match.group(1))
                        target_user = User.query.filter_by(user_id=found_user_id).first()
                        if target_user:
                            logger.info(f"✅ Tìm thấy user từ nội dung: {target_user.user_id}")
                
                # Cách 3: Tìm user từ database
                if not target_user:
                    # Thử tìm user gần đây nhất
                    target_user = User.query.order_by(User.last_active.desc()).first()
                    if target_user:
                        logger.info(f"✅ Tìm thấy user gần đây: {target_user.user_id}")
                
                # Cách 4: Tạo user mới nếu không tìm thấy
                if not target_user:
                    hash_obj = hashlib.md5(transaction_code.encode())
                    new_user_id = int(hash_obj.hexdigest()[:8], 16) % 1000000000
                    
                    target_user = User(
                        user_id=new_user_id,
                        username=f"user_{transaction_code[:4]}",
                        balance=0,
                        created_at=get_vn_time(),
                        last_active=get_vn_time()
                    )
                    db.session.add(target_user)
                    db.session.flush()
                    logger.info(f"🆕 TẠO USER MỚI: {target_user.user_id}")
                
                # ===== TẠO HOẶC CẬP NHẬT GIAO DỊCH =====
                if not existing:
                    transaction = Transaction(
                        user_id=target_user.id,
                        amount=amount,
                        type='deposit',
                        status='pending',
                        transaction_code=transaction_code,
                        description=f"NAP qua SePay",
                        created_at=get_vn_time()
                    )
                    db.session.add(transaction)
                    db.session.flush()
                    logger.info(f"✅ TẠO GIAO DỊCH MỚI: {transaction_code}")
                else:
                    transaction = existing
                
                # ===== KIỂM TRA SỐ TIỀN =====
                if abs(transaction.amount - amount) > 5000:
                    logger.error(f"❌ Số tiền không khớp: webhook={amount}, db={transaction.amount}")
                    # Cập nhật số tiền đúng từ webhook
                    transaction.amount = amount
                    logger.info(f"✅ Đã cập nhật số tiền: {amount}đ")
                
                # ===== CẬP NHẬT TRẠNG THÁI =====
                old_balance = target_user.balance
                target_user.balance += amount
                transaction.status = 'success'
                transaction.updated_at = get_vn_time()
                target_user.last_active = get_vn_time()
                
                # ===== COMMIT =====
                try:
                    db.session.commit()
                    logger.info(f"✅ COMMIT THÀNH CÔNG!")
                    logger.info(f"👤 User: {target_user.user_id}")
                    logger.info(f"💰 Số dư cũ: {old_balance:,}đ")
                    logger.info(f"💰 Số tiền nạp: +{amount:,}đ")
                    logger.info(f"💰 Số dư mới: {target_user.balance:,}đ")
                    logger.info(f"⏰ Thời gian: {get_vn_time().strftime('%H:%M:%S %d/%m/%Y')}")
                    
                    # Gửi thông báo Telegram
                    if BOT_TOKEN:
                        try:
                            message = (
                                f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                                f"• **Số tiền:** `{amount:,}đ`\n"
                                f"• **Mã GD:** `{transaction_code}`\n"
                                f"• **Số dư cũ:** `{old_balance:,}đ`\n"
                                f"• **Số dư mới:** `{target_user.balance:,}đ`\n"
                                f"• **Thời gian:** `{get_vn_time().strftime('%H:%M:%S %d/%m/%Y')}`"
                            )
                            asyncio.run(send_telegram_notification(target_user.user_id, message))
                        except Exception as e:
                            logger.error(f"❌ Lỗi gửi Telegram: {e}")
                    
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"❌ LỖI COMMIT: {e}")
                    return jsonify({"success": False, "error": "Database error"}), 500
                
                return jsonify({
                    "success": True,
                    "message": "Deposit processed successfully",
                    "data": {
                        "user_id": target_user.user_id,
                        "old_balance": old_balance,
                        "amount": amount,
                        "new_balance": target_user.balance,
                        "transaction_code": transaction_code,
                        "time": get_vn_time().isoformat()
                    }
                }), 200
                
        except Exception as e:
            logger.error(f"❌ LỖI WEBHOOK: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500