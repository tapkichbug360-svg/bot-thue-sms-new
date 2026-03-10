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
    # TẠM THỜI TẮT TRÊN RENDER - ĐỂ LOCAL XỬ LÝ
    logger.info(f"⏭️ BỎ QUA GỬI TELEGRAM TRÊN RENDER CHO USER {chat_id}")
    return

def setup_sepay_webhook(app):
    @app.route('/webhook/sepay', methods=['POST'])
    def sepay_webhook():
        try:
            data = request.json
            current_time = datetime.now()
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
                
                # ===== XÁC ĐỊNH USER - CHỈ DÙNG USER CÓ SẴN =====
                target_user = None
                
                # CÁCH 1: Tìm user_id trong nội dung (ƯU TIÊN NHẤT)
                user_match = re.search(r'tu[_\s]*(\d+)', content, re.IGNORECASE)
                if user_match:
                    found_user_id = int(user_match.group(1))
                    target_user = User.query.filter_by(user_id=found_user_id).first()
                    if target_user:
                        logger.info(f"✅ Cách 1: Tìm thấy user từ nội dung: {target_user.user_id}")
                
                # CÁCH 2: Tìm user_id dạng UID
                if not target_user:
                    uid_match = re.search(r'UID(\d+)', content, re.IGNORECASE)
                    if uid_match:
                        found_user_id = int(uid_match.group(1))
                        target_user = User.query.filter_by(user_id=found_user_id).first()
                        if target_user:
                            logger.info(f"✅ Cách 2: Tìm thấy user từ UID: {target_user.user_id}")
                
                # CÁCH 3: Tìm user_id dạng ID
                if not target_user:
                    id_match = re.search(r'ID(\d+)', content, re.IGNORECASE)
                    if id_match:
                        found_user_id = int(id_match.group(1))
                        target_user = User.query.filter_by(user_id=found_user_id).first()
                        if target_user:
                            logger.info(f"✅ Cách 3: Tìm thấy user từ ID: {target_user.user_id}")
                
                # CÁCH 4: Từ giao dịch có sẵn
                if not target_user and transaction:
                    target_user = User.query.get(transaction.user_id)
                    if target_user:
                        logger.info(f"✅ Cách 4: Tìm thấy user từ giao dịch: {target_user.user_id}")
                
                # CÁCH 5: Tìm user gần đây nhất
                if not target_user:
                    target_user = User.query.order_by(User.last_active.desc()).first()
                    if target_user:
                        logger.info(f"✅ Cách 5: Tìm thấy user gần đây: {target_user.user_id}")
                
                # NẾU KHÔNG TÌM THẤY USER -> TỪ CHỐI GIAO DỊCH
                if not target_user:
                    logger.error(f"❌ KHÔNG TÌM THẤY USER CHO GIAO DỊCH {transaction_code}")
                    return jsonify({
                        "success": False,
                        "error": "User not found"
                    }), 404
                
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
                logger.info(f"📌 Giao dịch {transaction_code} sẽ được local gửi thông báo sau khi đồng bộ")

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