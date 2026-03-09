from flask import request, jsonify
import logging
from bot import app
from database.models import User, Transaction, db
from datetime import datetime
import os
import re
import asyncio
import hashlib
from telegram import Bot

logger = logging.getLogger(__name__)

MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
BOT_TOKEN = os.getenv('BOT_TOKEN')

telegram_bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

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
            current_time = datetime.now()  # Định nghĩa ngay từ đầu
            logger.info("="*60)
            logger.info("📩 NHẬN WEBHOOK TỪ SEPAY")
            logger.info(f"Dữ liệu: {data}")
            
            transfer_type = data.get('transferType')
            account_number = data.get('accountNumber')
            amount = int(float(data.get('transferAmount', 0)))
            content = data.get('content', '').strip().upper()
            transaction_id = data.get('transactionId', '')
            
            if transfer_type != 'in':
                return jsonify({"success": True}), 200
            
            if account_number != MB_ACCOUNT:
                return jsonify({"success": True}), 200
            
            # Tìm mã GD
            transaction_code = None
            match = re.search(r'NAP\s*([A-Z0-9]{5,8})', content)
            if match:
                transaction_code = match.group(1)
                logger.info(f"🔍 Tìm thấy mã NAP: {transaction_code}")
            
            if not transaction_code:
                match = re.search(r'([A-Z0-9]{5,10})', content)
                if match:
                    transaction_code = match.group(1)
                    logger.info(f"🔍 Tìm thấy mã GD: {transaction_code}")
            
            if not transaction_code:
                logger.warning(f"⚠️ Không tìm thấy mã GD trong: {content}")
                return jsonify({"success": True}), 200
            
            with app.app_context():
                # Tìm giao dịch
                transaction = Transaction.query.filter_by(
                    transaction_code=transaction_code
                ).first()
                
                # Xác định user
                target_user = None
                
                if transaction:
                    target_user = User.query.get(transaction.user_id)
                    if target_user:
                        logger.info(f"✅ Tìm thấy user từ giao dịch: {target_user.user_id}")
                
                if not target_user:
                    user_match = re.search(r'tu[_\s]*(\d+)', content, re.IGNORECASE)
                    if user_match:
                        found_user_id = int(user_match.group(1))
                        target_user = User.query.filter_by(user_id=found_user_id).first()
                        if target_user:
                            logger.info(f"✅ Tìm thấy user từ nội dung: {target_user.user_id}")
                
                if not target_user:
                    hash_obj = hashlib.md5(transaction_code.encode())
                    new_user_id = int(hash_obj.hexdigest()[:8], 16) % 1000000000
                    
                    target_user = User(
                        user_id=new_user_id,
                        username=f"user_{transaction_code[:4]}",
                        balance=0,
                        created_at=current_time,
                        last_active=current_time
                    )
                    db.session.add(target_user)
                    db.session.flush()
                    logger.info(f"🆕 TẠO USER MỚI: {target_user.user_id}")
                
                # Xử lý giao dịch
                if not transaction:
                    transaction = Transaction(
                        user_id=target_user.id,
                        amount=amount,
                        type='deposit',
                        status='success',
                        transaction_code=transaction_code,
                        description=f"NAP qua SePay: {content}",
                        created_at=current_time,
                        updated_at=current_time
                    )
                    db.session.add(transaction)
                    logger.info(f"✅ TẠO GIAO DỊCH MỚI: {transaction_code}")
                else:
                    logger.info(f"🔄 Giao dịch {transaction_code} đã tồn tại, cộng thêm {amount}đ")
                    transaction.amount += amount
                    transaction.status = 'success'
                    transaction.updated_at = current_time
                
                # CỘNG TIỀN
                old_balance = target_user.balance
                target_user.balance += amount
                target_user.last_active = current_time
                
                db.session.commit()
                
                logger.info(f"✅ CẬP NHẬT THÀNH CÔNG!")
                logger.info(f"👤 User: {target_user.user_id}")
                logger.info(f"💰 {old_balance}đ → {target_user.balance}đ (+{amount}đ)")
                
                # Gửi Telegram
                if BOT_TOKEN:
                    message = (
                        f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                        f"• **Số tiền:** `{amount:,}đ`\n"
                        f"• **Mã GD:** `{transaction_code}`\n"
                        f"• **Số dư cũ:** `{old_balance:,}đ`\n"
                        f"• **Số dư mới:** `{target_user.balance:,}đ`\n"
                        f"• **Thời gian:** `{current_time.strftime('%H:%M:%S %d/%m/%Y')}`"
                    )
                    asyncio.run(send_telegram_notification(target_user.user_id, message))
                
                return jsonify({
                    "success": True,
                    "data": {
                        "user_id": target_user.user_id,
                        "old_balance": old_balance,
                        "amount": amount,
                        "new_balance": target_user.balance,
                        "transaction_code": transaction_code,
                        "time": current_time.isoformat()
                    }
                }), 200
                
        except Exception as e:
            logger.error(f"❌ LỖI WEBHOOK: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False}), 500