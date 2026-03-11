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
import requests
import threading
import time
import json
import secrets

logger = logging.getLogger(__name__)

MB_ACCOUNT = os.getenv('MB_ACCOUNT', '666666291005')
MB_NAME = os.getenv('MB_NAME', 'NGUYEN THE LAM')
BOT_TOKEN = os.getenv('BOT_TOKEN')

telegram_bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

# ===== CẤU HÌNH ĐỒNG BỘ =====
RENDER_URL = os.getenv('RENDER_URL', 'https://bot-thue-sms-new.onrender.com')
LOCAL_URL = os.getenv('LOCAL_URL', 'http://localhost:5000')  # URL của dashboard local
SYNC_ENABLED = True

# Cache để tránh đồng bộ vòng lặp vô hạn
processed_transactions = set()
last_sync_time = datetime.now()

# ===== HÀM GỬI TELEGRAM ĐỒNG BỘ =====
def send_telegram_sync(chat_id, message):
    """Gửi Telegram đồng bộ"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"📨 Đã gửi Telegram cho user {chat_id}")
            return True
        else:
            logger.warning(f"⚠️ Telegram lỗi {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Lỗi gửi Telegram: {e}")
        return False

# ===== HÀM ĐỒNG BỘ LÊN RENDER =====
def sync_to_render(user_data):
    """Đồng bộ dữ liệu user lên Render"""
    if not SYNC_ENABLED:
        return
    
    try:
        # Tránh trùng lặp
        tx_key = f"sync_{user_data.get('user_id')}_{int(time.time())}"
        if tx_key in processed_transactions:
            return
        
        # Đồng bộ qua nhiều API để đảm bảo thành công
        apis = [
            f"{RENDER_URL}/api/update-balance"
        ]
        
        for api in apis:
            try:
                response = requests.post(
                    api,
                    json=user_data,
                    timeout=3
                )
                if response.status_code == 200:
                    logger.info(f"✅ Đồng bộ lên Render thành công qua {api}")
                    processed_transactions.add(tx_key)
                    
                    # Xóa cache cũ
                    if len(processed_transactions) > 100:
                        processed_transactions.clear()
                    return True
            except:
                continue
        
        logger.warning(f"⚠️ Không thể đồng bộ lên Render qua bất kỳ API nào")
        return False
        
    except Exception as e:
        logger.error(f"❌ Lỗi đồng bộ lên Render: {e}")
        return False

# ===== HÀM LẤY DỮ LIỆU TỪ LOCAL DASHBOARD =====
def fetch_from_local():
    """Lấy dữ liệu mới nhất từ Local Dashboard"""
    try:
        response = requests.get(
            f"{LOCAL_URL}/api/get-all-users",
            timeout=3
        )
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

# ===== HÀM ĐỒNG BỘ XUỐNG LOCAL =====
def sync_to_local(transaction_data):
    """Đồng bộ giao dịch xuống Local Dashboard"""
    if not SYNC_ENABLED:
        return
    
    try:
        # Tránh trùng lặp
        tx_id = transaction_data.get('transaction_code', '')
        if tx_id in processed_transactions:
            return
        
        # Gửi đến local dashboard
        response = requests.post(
            f"{LOCAL_URL}/api/receive-sync",
            json={
                'type': 'sepay_transaction',
                'data': transaction_data,
                'timestamp': datetime.now().isoformat()
            },
            timeout=3
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Đồng bộ xuống Local thành công: {tx_id}")
            processed_transactions.add(tx_id)
            
            # Xóa cache cũ
            if len(processed_transactions) > 100:
                processed_transactions.clear()
            return True
        else:
            logger.warning(f"⚠️ Local trả về lỗi: {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Lỗi đồng bộ xuống Local: {e}")
    
    return False

# ===== HÀM ĐỒNG BỘ 2 CHIỀU =====
def bidirectional_sync(user_data, transaction_data=None):
    """Đồng bộ 2 chiều: Lên Render và Xuống Local"""
    
    # 1. Đồng bộ lên Render
    sync_to_render(user_data)
    
    # 2. Nếu có giao dịch, đồng bộ xuống Local
    if transaction_data:
        sync_to_local(transaction_data)
    
    # 3. Lấy dữ liệu mới từ Local để kiểm tra
    local_data = fetch_from_local()
    if local_data:
        logger.info(f"📊 Local dashboard có {len(local_data)} users")

# ===== API CHO LOCAL DASHBOARD GỌI =====
@app.route('/api/receive-sync', methods=['POST'])
def receive_sync():
    """Nhận đồng bộ từ Local Dashboard"""
    try:
        data = request.json
        sync_type = data.get('type')
        
        if sync_type == 'manual_transaction':
            # Có giao dịch thủ công từ Local
            user_id = data.get('user_id')
            amount = data.get('amount')
            tx_code = data.get('transaction_code')
            
            logger.info(f"📥 Nhận đồng bộ từ Local: {'Cộng' if amount > 0 else 'Trừ'} {abs(amount)}đ cho user {user_id}")
            
            # Cập nhật vào database của bot
            with app.app_context():
                user = User.query.filter_by(user_id=user_id).first()
                if user:
                    old_balance = user.balance
                    
                    # Cập nhật balance
                    user.balance += amount
                    
                    # Tạo transaction
                    transaction = Transaction(
                        user_id=user.id,
                        amount=abs(amount),
                        type='deposit' if amount > 0 else 'deduct',
                        status='success',
                        transaction_code=tx_code,
                        description=f"Đồng bộ từ Dashboard: {data.get('reason', '')}",
                        created_at=datetime.now()
                    )
                    db.session.add(transaction)
                    db.session.commit()
                    
                    logger.info(f"✅ Đã đồng bộ từ Local: User {user_id} balance {old_balance} → {user.balance}")
                    
                    return jsonify({
                        'success': True,
                        'message': 'Đã đồng bộ thành công'
                    })
        
        elif sync_type == 'request_sync':
            # Yêu cầu đồng bộ tất cả users
            users = []
            with app.app_context():
                all_users = User.query.all()
                for u in all_users:
                    users.append({
                        'user_id': u.user_id,
                        'balance': u.balance,
                        'username': u.username
                    })
            
            return jsonify({
                'success': True,
                'users': users,
                'count': len(users)
            })
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"❌ Lỗi receive_sync: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API ĐỒNG BỘ 2 CHIỀU CHO RENDER =====
@app.route('/api/sync-bidirectional', methods=['POST'])
def sync_bidirectional():
    """API đồng bộ 2 chiều (Render gọi xuống)"""
    try:
        data = request.json
        user_id = data.get('user_id')
        balance = data.get('balance')

        if not user_id:
            return jsonify({'success': False, 'error': 'Thiếu user_id'}), 400

        with app.app_context():
            user = User.query.filter_by(user_id=user_id).first()

            if not user:
                # Tạo user mới nếu chưa có
                user = User(
                    user_id=user_id,
                    username=data.get('username', f'user_{user_id}'),
                    balance=int(balance) if balance is not None else 0,
                    created_at=datetime.now()
                )
                db.session.add(user)
                logger.info(f"✅ Tạo user mới từ đồng bộ: {user_id}")

            else:
                if balance is not None:

                    balance = int(balance)
                    old = user.balance

                    # ===== FIX: KHÔNG GHI ĐÈ BALANCE =====
                    if balance > old:
                        diff = balance - old
                        user.balance += diff
                        logger.info(
                            f"🔼 Sync cộng {diff} cho user {user_id}: {old} → {user.balance}"
                        )

                    elif balance < old:
                        diff = old - balance
                        user.balance -= diff
                        logger.info(
                            f"🔽 Sync trừ {diff} cho user {user_id}: {old} → {user.balance}"
                        )

                    else:
                        logger.info(
                            f"⏭️ Balance không thay đổi ({balance})"
                        )

            db.session.commit()

            return jsonify({
                'success': True,
                'user_id': user.user_id,
                'balance': user.balance
            })

    except Exception as e:
        logger.error(f"❌ Lỗi sync_bidirectional: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== WEBHOOK CHÍNH - ĐÃ FIX LỖI NẠP NHIỀU LẦN =====
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
                logger.info(f"⏭️ Bỏ qua giao dịch {transfer_type} (không phải tiền vào)")
                return jsonify({"success": True}), 200
            
            if account_number != MB_ACCOUNT:
                logger.info(f"⏭️ Bỏ qua giao dịch tài khoản {account_number} (không phải MB {MB_ACCOUNT})")
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
                
                if transaction:
                    logger.info(f"📝 ĐÃ TÌM THẤY TRANSACTION CŨ: ID={transaction.id}, amount={transaction.amount}")
                else:
                    logger.info(f"📝 CHƯA CÓ TRANSACTION NÀY, sẽ tạo mới")
                
                # ===== XÁC ĐỊNH USER =====
                target_user = None
                
                # CÁCH 1: Tìm user_id trong nội dung
                user_match = re.search(r'tu[_\s]*(\d+)', content, re.IGNORECASE)
                if user_match:
                    found_user_id = int(user_match.group(1))
                    target_user = User.query.filter_by(user_id=found_user_id).first()
                    if target_user:
                        logger.info(f"✅ Cách 1: Tìm thấy user {target_user.user_id} từ nội dung")
                
                # CÁCH 2: Tìm user_id dạng UID
                if not target_user:
                    uid_match = re.search(r'UID(\d+)', content, re.IGNORECASE)
                    if uid_match:
                        found_user_id = int(uid_match.group(1))
                        target_user = User.query.filter_by(user_id=found_user_id).first()
                        if target_user:
                            logger.info(f"✅ Cách 2: Tìm thấy user {target_user.user_id} từ UID")
                
                # CÁCH 3: Tìm user_id dạng ID
                if not target_user:
                    id_match = re.search(r'ID(\d+)', content, re.IGNORECASE)
                    if id_match:
                        found_user_id = int(id_match.group(1))
                        target_user = User.query.filter_by(user_id=found_user_id).first()
                        if target_user:
                            logger.info(f"✅ Cách 3: Tìm thấy user {target_user.user_id} từ ID")
                
                # CÁCH 4: Từ giao dịch có sẵn
                if not target_user and transaction:
                    target_user = User.query.get(transaction.user_id)
                    if target_user:
                        logger.info(f"✅ Cách 4: Tìm thấy user {target_user.user_id} từ giao dịch")
                
                # CÁCH 5: Tìm user gần đây nhất
                if not target_user:
                    target_user = User.query.order_by(User.last_active.desc()).first()
                    if target_user:
                        logger.warning(f"⚠️ Cách 5: Dùng user gần đây {target_user.user_id} (FALLBACK)")
                
                if not target_user:
                    logger.error(f"❌ KHÔNG TÌM THẤY USER CHO GIAO DỊCH {transaction_code}")
                    return jsonify({
                        "success": False,
                        "error": "User not found"
                    }), 404
                
                logger.info(f"👤 USER: {target_user.user_id}, Username: {target_user.username}")
                logger.info(f"💰 BALANCE HIỆN TẠI TRONG DB: {target_user.balance}")
                
                # ===== XỬ LÝ GIAO DỊCH - LUÔN CỘNG TIỀN =====
                old_balance = target_user.balance

                # LUÔN CỘNG TIỀN - KHÔNG BAO GIỜ BỎ QUA
                target_user.balance += amount
                logger.info(f"💰 ĐÃ CỘNG {amount} VÀO BALANCE: {old_balance} → {target_user.balance}")
                
                # KIỂM TRA BẰNG LOG CẤP CAO NHẤT
                print(f"🔴🔴🔴 KIỂM TRA: ĐÃ CỘNG {amount}, BALANCE={target_user.balance}")
                logger.critical(f"🔴🔴🔴 KIỂM TRA: ĐÃ CỘNG {amount}, BALANCE={target_user.balance}")

                # XỬ LÝ TRANSACTION - TẠO MỚI CHO MỖI LẦN NẠP
                if not transaction:
                    # Tạo transaction mới
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
                    logger.info(f"✅ TẠO TRANSACTION MỚI: {transaction_code}")
                else:
                    # TẠO TRANSACTION MỚI CHO LẦN NẠP NÀY (KHÔNG CỘNG DỒN)
                    # Thêm timestamp và random để tránh trùng mã
                    timestamp = int(time.time() * 1000)
                    random_suffix = secrets.token_hex(2).upper()
                    new_code = f"{transaction_code}_{timestamp}_{random_suffix}"[-50:]  # Giới hạn độ dài
                    
                    new_transaction = Transaction(
                        user_id=target_user.id,
                        amount=amount,
                        type='deposit',
                        status='success',
                        transaction_code=new_code,
                        description=f"NAP qua SePay (lần {transaction.amount + 1}): {content}",
                        created_at=current_time,
                        updated_at=current_time
                    )
                    db.session.add(new_transaction)
                    logger.info(f"✅ TẠO TRANSACTION MỚI CHO LẦN NẠP THỨ {transaction.amount + 1}: {new_code}")
                    
                    # Cập nhật để dùng transaction mới cho phần sau
                    transaction = new_transaction

                # Cập nhật thời gian
                target_user.last_active = current_time

                # COMMIT
                try:
                    db.session.commit()
                    logger.info(f"✅ COMMIT THÀNH CÔNG! Balance: {target_user.balance}")
                except Exception as e:
                    logger.error(f"❌ COMMIT LỖI: {e}")
                    db.session.rollback()
                    return jsonify({"success": False}), 500

                logger.info(f"💰 {old_balance}đ → {target_user.balance}đ (+{amount}đ)")
                logger.info(f"✅ CẬP NHẬT THÀNH CÔNG CHO USER {target_user.user_id}!")
                
                # ===== GỬI TELEGRAM NGAY LẬP TỨC =====
                try:
                    current_time_str = current_time.strftime('%H:%M:%S %d/%m/%Y')
                    message = (
                        f"💰 **NẠP TIỀN THÀNH CÔNG!**\n\n"
                        f"• **Số tiền:** +{amount:,}đ\n"
                        f"• **Số dư mới:** {target_user.balance:,}đ\n"
                        f"• **Mã GD:** `{transaction.transaction_code}`\n"
                        f"• **Thời gian:** {current_time_str}"
                    )
                    
                    # Gửi Telegram
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    payload = {
                        'chat_id': target_user.user_id,
                        'text': message,
                        'parse_mode': 'Markdown'
                    }
                    response = requests.post(url, json=payload, timeout=10)
                    
                    if response.status_code == 200:
                        logger.info(f"📨 Đã gửi Telegram cho user {target_user.user_id}")
                    else:
                        logger.warning(f"⚠️ Telegram lỗi {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"❌ Lỗi gửi Telegram: {e}")
                
                # ===== ĐỒNG BỘ 2 CHIỀU =====
                try:
                    # Chuẩn bị dữ liệu user để đồng bộ
                    user_data = {
                        'user_id': target_user.user_id,
                        'balance': target_user.balance,
                        'username': target_user.username or f"user_{target_user.user_id}"
                    }
                    
                    # Chuẩn bị dữ liệu giao dịch để đồng bộ xuống Local
                    transaction_data = {
                        'transaction_code': transaction.transaction_code,
                        'user_id': target_user.user_id,
                        'amount': amount,
                        'type': 'deposit',
                        'time': current_time.isoformat(),
                        'description': f"NAP qua SePay: {content}"
                    }
                    
                    # Đồng bộ 2 chiều
                    sync_to_render(user_data)
                    
                except Exception as e:
                    logger.error(f"❌ Lỗi đồng bộ: {e}")
                
                logger.info(f"📌 Giao dịch {transaction.transaction_code} hoàn tất")

                return jsonify({
                    "success": True,
                    "data": {
                        "user_id": target_user.user_id,
                        "old_balance": old_balance,
                        "amount": amount,
                        "new_balance": target_user.balance,
                        "transaction_code": transaction.transaction_code,
                        "time": current_time.isoformat()
                    }
                }), 200
                
        except Exception as e:
            logger.error(f"❌ LỖI WEBHOOK: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False}), 500

    # ===== API ĐỒNG BỘ ĐỊNH KỲ =====
    @app.route('/api/force-sync', methods=['POST'])
    def force_sync():
        """API để đồng bộ cưỡng chế tất cả dữ liệu"""
        try:
            with app.app_context():
                users = User.query.all()
                sync_data = []
                
                for u in users:
                    sync_data.append({
                        'user_id': u.user_id,
                        'balance': u.balance,
                        'username': u.username
                    })
                
                # Đồng bộ lên Render
                for user_data in sync_data:
                    sync_to_render(user_data)
                
                return jsonify({
                    'success': True,
                    'synced': len(sync_data),
                    'users': sync_data
                })
                
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ===== API KIỂM TRA ĐỒNG BỘ =====
    @app.route('/api/sync-status', methods=['GET'])
    def sync_status():
        return jsonify({
            'status': 'active',
            'sync_enabled': SYNC_ENABLED,
            'render_url': RENDER_URL,
            'local_url': LOCAL_URL,
            'processed_count': len(processed_transactions),
            'last_sync': last_sync_time.isoformat() if last_sync_time else None
        })