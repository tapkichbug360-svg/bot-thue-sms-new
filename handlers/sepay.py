from flask import request, jsonify
import logging
from bot import app
from database.models import User, Transaction, db
from datetime import datetime, timedelta
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
            
            # Lấy thời gian giao dịch từ SePay
            transaction_date_str = data.get('transactionDate', '')
            try:
                transaction_time = datetime.strptime(transaction_date_str, '%Y-%m-%d %H:%M:%S')
            except:
                transaction_time = current_time
                logger.warning(f"⚠️ Không parse được thời gian, dùng thời gian hiện tại")
            
            # Tính độ chênh lệch thời gian
            time_diff = current_time - transaction_time
            minutes_diff = time_diff.total_seconds() / 60
            
            logger.info(f"⏰ Thời gian giao dịch: {transaction_time}")
            logger.info(f"⏰ Thời gian hiện tại: {current_time}")
            logger.info(f"⏱️ Chênh lệch: {minutes_diff:.1f} phút")
            
            if transfer_type != 'in':
                return jsonify({"success": True}), 200
            
            if account_number != MB_ACCOUNT:
                return jsonify({"success": True}), 200
            
            # ===== KIỂM TRA SỐ TIỀN TỐI THIỂU =====
            if amount < 20000:
                logger.warning(f"⚠️ TỪ CHỐI GIAO DỊCH DƯỚI 20,000đ: {amount}đ")
                return jsonify({
                    "success": False,
                    "error": "Số tiền tối thiểu là 20,000đ"
                }), 400
            
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
                # Tìm giao dịch cũ
                existing_transaction = Transaction.query.filter_by(
                    transaction_code=transaction_code
                ).first()
                
                # ===== XÁC ĐỊNH USER =====
                target_user = None
                
                # CÁCH 1: Tìm user_id trong nội dung
                user_match = re.search(r'tu[_\s]*(\d+)', content, re.IGNORECASE)
                if user_match:
                    found_user_id = int(user_match.group(1))
                    target_user = User.query.filter_by(user_id=found_user_id).first()
                    if target_user:
                        logger.info(f"✅ Tìm thấy user {target_user.user_id} từ nội dung")
                
                # CÁCH 2: Từ giao dịch cũ
                if not target_user and existing_transaction:
                    target_user = User.query.get(existing_transaction.user_id)
                    if target_user:
                        logger.info(f"✅ Tìm thấy user {target_user.user_id} từ giao dịch cũ")
                
                # CÁCH 3: User gần đây nhất
                if not target_user:
                    target_user = User.query.order_by(User.last_active.desc()).first()
                    if target_user:
                        logger.warning(f"⚠️ Dùng user gần đây {target_user.user_id}")
                
                if not target_user:
                    logger.error(f"❌ KHÔNG TÌM THẤY USER")
                    return jsonify({"success": False, "error": "User not found"}), 404
                
                # ===== KIỂM TRA THỜI GIAN =====
                if minutes_diff > 60:  # Quá 60 phút
                    logger.warning(f"⚠️ GIAO DỊCH QUÁ CŨ ({minutes_diff:.1f} phút) - TỪ CHỐI")
                    return jsonify({
                        "success": False,
                        "error": "Giao dịch quá cũ, vui lòng tạo mã mới"
                    }), 400
                
                # ===== XỬ LÝ GIAO DỊCH =====
                if existing_transaction:
                    # Đã có giao dịch, kiểm tra user
                    old_user = User.query.get(existing_transaction.user_id)
                    
                    if old_user and old_user.user_id == target_user.user_id:
                        # CÙNG USER - Chỉ cho phép nếu trong thời gian ngắn
                        if minutes_diff < 5:  # Dưới 5 phút
                            logger.info(f"🔄 Cùng user, cộng dồn {amount}đ (trong {minutes_diff:.1f} phút)")
                            existing_transaction.amount += amount
                            existing_transaction.updated_at = current_time
                            
                            old_balance = target_user.balance
                            target_user.balance += amount
                            target_user.last_active = current_time
                            
                            db.session.commit()
                            
                            logger.info(f"✅ CỘNG DỒN THÀNH CÔNG!")
                            logger.info(f"💰 {old_balance}đ → {target_user.balance}đ (+{amount}đ)")
                            
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
                        else:
                            # Quá 5 phút
                            logger.warning(f"⚠️ Cùng user nhưng quá 5 phút ({minutes_diff:.1f}) - Từ chối")
                            return jsonify({
                                "success": False,
                                "error": "Bạn đã dùng mã này quá 5 phút trước"
                            }), 400
                    else:
                        # USER KHÁC - Cho phép nếu trong vòng 60 phút
                        logger.info(f"✅ User khác dùng mã {transaction_code} (cách {minutes_diff:.1f} phút)")
                        # Tạo giao dịch mới
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
                        
                        old_balance = target_user.balance
                        target_user.balance += amount
                        target_user.last_active = current_time
                        
                        db.session.commit()
                        
                        logger.info(f"✅ TẠO GIAO DỊCH MỚI CHO USER {target_user.user_id}")
                        logger.info(f"💰 {old_balance}đ → {target_user.balance}đ (+{amount}đ)")
                        
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
                else:
                    # Giao dịch mới hoàn toàn
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
                    
                    old_balance = target_user.balance
                    target_user.balance += amount
                    target_user.last_active = current_time
                    
                    db.session.commit()
                    
                    logger.info(f"✅ TẠO GIAO DỊCH MỚI CHO USER {target_user.user_id}")
                    logger.info(f"💰 {old_balance}đ → {target_user.balance}đ (+{amount}đ)")
                    
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