from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, unique=True, nullable=False)
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
    user_id = db.Column(db.BigInteger, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending')
    transaction_code = db.Column(db.String(100), unique=True)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class Rental(db.Model):
    __tablename__ = 'rentals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False)
    service_id = db.Column(db.Integer, nullable=False)
    service_name = db.Column(db.String(100))
    phone_number = db.Column(db.String(20))
    otp_id = db.Column(db.Integer)
    sim_id = db.Column(db.Integer)
    cost = db.Column(db.Integer)
    price_charged = db.Column(db.Integer)
    status = db.Column(db.String(20), default='waiting')
    otp_code = db.Column(db.String(50))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    expires_at = db.Column(db.DateTime)
    audio_url = db.Column(db.String(500), nullable=True)  # URL file audio OTP

def init_db():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'bot.db')
    return f'sqlite:///{db_path}'
