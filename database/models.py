from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(100))
    balance = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Integer, default=0)
    total_rentals = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_active = db.Column(db.DateTime, default=datetime.now)
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending', index=True)
    transaction_code = db.Column(db.String(100), unique=True, index=True)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class Rental(db.Model):
    __tablename__ = 'rentals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    service_id = db.Column(db.Integer, nullable=False, index=True)
    service_name = db.Column(db.String(100))
    phone_number = db.Column(db.String(20), index=True)
    otp_id = db.Column(db.Integer)
    sim_id = db.Column(db.Integer)
    cost = db.Column(db.Integer)
    price_charged = db.Column(db.Integer)
    status = db.Column(db.String(20), default='waiting', index=True)
    otp_code = db.Column(db.String(50))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    expires_at = db.Column(db.DateTime, index=True)
    audio_url = db.Column(db.String(500), nullable=True)
    refunded = db.Column(db.Boolean, default=False, index=True)
    auto_refunded = db.Column(db.Boolean, default=False)
    refund_amount = db.Column(db.Integer, default=0)
    refunded_at = db.Column(db.DateTime, nullable=True)

class DepositTransaction(db.Model):
    __tablename__ = 'deposit_transactions'
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending', index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    processed_at = db.Column(db.DateTime, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    webhook_data = db.Column(db.Text, nullable=True)

class BalanceLog(db.Model):
    """Lưu lịch sử thay đổi số dư"""
    __tablename__ = 'balance_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    old_balance = db.Column(db.Integer, nullable=False)
    new_balance = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50))  # 'rent', 'cancel', 'auto_refund', 'deposit'
    rental_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)

class PushedTransaction(db.Model):
    __tablename__ = 'pushed_transactions'
    id = db.Column(db.Integer, primary_key=True)
    transaction_code = db.Column(db.String(50), unique=True, index=True)
    pushed_at = db.Column(db.DateTime, default=datetime.now, index=True)

# ===== THÊM BẢNG MỚI - KHÔNG ẢNH HƯỞNG CẤU TRÚC CŨ =====
class SyncedTransaction(db.Model):
    """Lưu các giao dịch đã được đồng bộ để tránh đồng bộ lại"""
    __tablename__ = 'synced_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    transaction_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    synced_at = db.Column(db.DateTime, default=datetime.now, index=True)
    transaction_time = db.Column(db.DateTime, nullable=True)  # Thời gian gốc của giao dịch
    source = db.Column(db.String(20), default='sepay')  # 'sepay', 'manual', 'daemon'
    
    def __repr__(self):
        return f'<SyncedTransaction {self.transaction_code}>'

def init_db():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'bot.db')
    return f'sqlite:///{db_path}'