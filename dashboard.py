# -*- coding: utf-8 -*-
"""
Bot Thuê SMS - Dashboard Quản Trị Chuyên Nghiệp
Phiên bản tối ưu toàn diện, việt hóa 100%.
"""

import csv
import io
import json
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta

import requests
from flask import (Flask, Response, flash, jsonify, redirect,
                   render_template_string, request, url_for)
from flask_sqlalchemy import SQLAlchemy

# ====================== CẤU HÌNH LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ====================== KHỞI TẠO APP ======================
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# ====================== CẤU HÌNH DATABASE ======================
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'bot.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ====================== API & TELEGRAM CONFIG ======================
API_KEY = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ6emxhbXp6MTEyMiIsImp0aSI6IjgwNTYwIiwiaWF0IjoxNzYxNjEyODAzLCJleHAiOjE4MjM4MjA4MDN9.4u-0IEkd2dgB6QtLEMlgp0KG55JwDDfMiNd98BQNzuJljOA9UTDymPsqnheIqGFM7WVGx94iV71tZasx62JIvw"
BASE_URL = "https://apisim.codesim.net"
BOT_TOKEN = os.getenv('BOT_TOKEN', '8561464326:AAG6NPFNvvFV0vFWQP1t8qUMo3WrjW5Un90')
RENDER_URL = "https://bot-thue-sms-new.onrender.com"  # URL đồng bộ (có thể thay đổi)

# ====================== ĐỊNH NGHĨA MODEL ======================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, unique=True, nullable=False)
    username = db.Column(db.String(100))
    balance = db.Column(db.Integer, default=0)
    total_rentals = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Integer, default=0)
    is_banned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_active = db.Column(db.DateTime, default=datetime.now)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    amount = db.Column(db.Integer)
    type = db.Column(db.String(20))          # deposit, deduct
    status = db.Column(db.String(20))        # success, pending, failed
    transaction_code = db.Column(db.String(100), unique=True)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)

class Rental(db.Model):
    __tablename__ = 'rentals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    service_name = db.Column(db.String(100))
    phone_number = db.Column(db.String(20))
    price_charged = db.Column(db.Integer)
    cost = db.Column(db.Integer)
    status = db.Column(db.String(20))        # waiting, success, cancelled, expired
    otp_code = db.Column(db.String(50))
    otp_id = db.Column(db.String(100))
    sim_id = db.Column(db.String(100))
    refunded = db.Column(db.Boolean, default=False)
    refund_amount = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)

# ====================== HÀM TIỆN ÍCH ======================
def format_currency(amount):
    """Định dạng tiền VNĐ"""
    return f"{amount:,}đ"

def send_telegram_notification(user_id, message):
    """Gửi thông báo Telegram đến user"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"✅ Đã gửi Telegram đến user {user_id}")
            return True
        else:
            logger.warning(f"⚠️ Telegram lỗi {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Lỗi gửi Telegram: {e}")
        return False

def send_bulk_telegram(user_ids, message, from_user=None):
    """Gửi tin nhắn hàng loạt đến nhiều user"""
    success = 0
    failed = 0
    for user_id in user_ids:
        try:
            full_message = message
            if from_user:
                full_message += f"\n\n— Admin {from_user}"
            if send_telegram_notification(user_id, full_message):
                success += 1
            else:
                failed += 1
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Lỗi gửi cho user {user_id}: {e}")
            failed += 1
    return success, failed

def save_failed_push(user_id, balance, username, transaction_code, amount):
    """Lưu push thất bại để xử lý sau"""
    try:
        failed_file = 'failed_pushes_dashboard.json'
        failed = []
        if os.path.exists(failed_file):
            with open(failed_file, 'r') as f:
                failed = json.load(f)
        failed.append({
            'user_id': user_id,
            'balance': balance,
            'username': username,
            'transaction_code': transaction_code,
            'amount': amount,
            'time': datetime.now().isoformat(),
            'source': 'dashboard'
        })
        # Giữ 50 entry gần nhất
        if len(failed) > 50:
            failed = failed[-50:]
        with open(failed_file, 'w') as f:
            json.dump(failed, f, indent=2)
        logger.info(f"💾 Đã lưu push thất bại cho user {user_id}")
    except Exception as e:
        logger.error(f"❌ Lỗi lưu failed push: {e}")

# ====================== BASE TEMPLATE (VIỆT HÓA, TỐI ƯU) ======================
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Thuê SMS - Dashboard Quản Trị</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.7/css/dataTables.bootstrap5.min.css">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        :root {
            --primary: #6366f1;
            --primary-dark: #4f46e5;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
        }
        body { background: #f8fafc; font-family: 'Segoe UI', system-ui, sans-serif; }
        .navbar {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            box-shadow: 0 10px 30px rgba(99, 102, 241, 0.3);
        }
        .navbar-brand { font-weight: 700; font-size: 1.4rem; letter-spacing: -0.5px; }
        .card {
            border: none;
            border-radius: 20px;
            box-shadow: 0 10px 35px rgba(0,0,0,0.08);
            transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .card:hover { transform: translateY(-10px); box-shadow: 0 25px 50px rgba(0,0,0,0.15); }
        .card-header {
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
            border-radius: 20px 20px 0 0 !important;
            font-weight: 600;
        }
        .stat-card {
            background: white;
            border-radius: 20px;
            padding: 30px 20px;
            text-align: center;
            transition: all 0.3s;
        }
        .stat-card:hover { transform: scale(1.06); }
        .stat-number { font-size: 2.9rem; font-weight: 700; color: var(--primary); }
        .profit-number { font-size: 2.9rem; font-weight: 700; color: var(--success); }
        .table thead { background: linear-gradient(135deg, var(--primary), var(--primary-dark)); color: white; }
        .status-success { background: #10b981; color: white; padding: 6px 16px; border-radius: 50px; font-size: 0.85rem; font-weight: 500; }
        .status-cancel { background: #ef4444; color: white; padding: 6px 16px; border-radius: 50px; font-size: 0.85rem; font-weight: 500; }
        .status-pending { background: #f59e0b; color: white; padding: 6px 16px; border-radius: 50px; font-size: 0.85rem; font-weight: 500; }
        .search-box { border-radius: 50px; padding: 14px 24px; border: 2px solid #e2e8f0; font-size: 1.05rem; }
        .flash-message { position: fixed; top: 25px; right: 25px; z-index: 99999; animation: slideIn 0.5s ease; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
        @keyframes slideIn { from { transform: translateX(150%); } to { transform: translateX(0); } }
        .modal-content { border-radius: 20px; }
        .dataTables_wrapper .dataTables_filter input { border-radius: 50px; padding: 10px 20px; }
        .nav-link { transition: all 0.3s; }
        .nav-link:hover { background: rgba(255,255,255,0.15); border-radius: 10px; }
        .badge-count { font-size: 0.8rem; padding: 0.4rem 0.6rem; }
        .message-preview { max-height: 200px; overflow-y: auto; background: #f8f9fa; padding: 15px; border-radius: 10px; }
        .highlight-update {
            animation: highlight 1s ease;
        }
        @keyframes highlight {
            0% { background-color: #d1fae5; }
            100% { background-color: transparent; }
        }
        .otp-code {
            background: #28a745;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
            animation: pulse 1s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }
        .table-success {
            background-color: #d4edda !important;
        }
        .time-cell {
            font-family: monospace;
            font-weight: bold;
        }
        .phone-number {
            font-size: 1.1em;
            font-weight: 500;
        }
    </style>
</head>
<body>
    <!-- ĐỒNG HỒ LIVE -->
    <script>
        function updateClock() {
            const now = new Date();
            const hours = now.getHours().toString().padStart(2, '0');
            const minutes = now.getMinutes().toString().padStart(2, '0');
            const seconds = now.getSeconds().toString().padStart(2, '0');
            const day = now.getDate().toString().padStart(2, '0');
            const month = (now.getMonth() + 1).toString().padStart(2, '0');
            const year = now.getFullYear();
            const clockElement = document.getElementById('liveClock');
            if (clockElement) {
                clockElement.innerHTML = `<i class="bi bi-clock-history me-1"></i>${hours}:${minutes}:${seconds} ${day}/${month}/${year}`;
            }
        }
        updateClock();
        setInterval(updateClock, 1000);
    </script>

    <!-- FLASH MESSAGES -->
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }} alert-dismissible fade show flash-message" role="alert">
                    {{ message | safe }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <nav class="navbar navbar-expand-lg navbar-dark py-3">
        <div class="container">
            <a class="navbar-brand" href="/"><i class="bi bi-telephone-fill me-2"></i>Bot Thuê SMS - Quản Trị</a>
            <div class="collapse navbar-collapse">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item"><a class="nav-link px-4" href="/"><i class="bi bi-house-door-fill"></i> Dashboard</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/users"><i class="bi bi-people-fill"></i> Người dùng</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/transactions"><i class="bi bi-cash-stack"></i> Giao dịch</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/profit"><i class="bi bi-graph-up-arrow"></i> Lợi nhuận</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/manual"><i class="bi bi-plus-circle-fill"></i> Cộng tiền</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/deduct"><i class="bi bi-dash-circle-fill text-warning"></i> Trừ tiền</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/broadcast"><i class="bi bi-megaphone-fill text-info"></i> Gửi tin</a></li>
                    <li class="nav-item"><a class="nav-link px-4" href="/statistics"><i class="bi bi-bar-chart-line"></i> Thống kê</a></li>
                    <li class="nav-item"><span class="nav-link text-white-50" id="liveClock"><i class="bi bi-clock-history me-1"></i>Đang tải...</span></li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-5">
        {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.7/js/jquery.dataTables.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.7/js/dataTables.bootstrap5.min.js"></script>
    <script>
        // Khởi tạo DataTables
        $(document).ready(function() {
            $('.datatable').DataTable({
                language: { url: '//cdn.datatables.net/plug-ins/1.13.7/i18n/vi.json' },
                pageLength: 15,
                responsive: true,
                order: [[0, 'desc']]
            });
        });

        // Các biến toàn cục
        let selectedUsers = [];
        let currentUserId = null;
        let lastUpdateTime = {};

        // ==================== HÀM CẬP NHẬT REALTIME ====================
        function updateRealtimeData() {
            const path = window.location.pathname;
            const timestamp = new Date().getTime();

            // Kiểm tra giao dịch mới
            fetch('/api/realtime-transactions?_=' + timestamp)
                .then(response => response.json())
                .then(data => {
                    if (data.updates && data.updates > 0) {
                        showNotification('📊 Có ' + data.updates + ' giao dịch mới!', 'info');
                        // Tùy theo trang hiện tại, cập nhật dữ liệu
                        if (path === '/') {
                            updateDashboard();
                            updateRecentTransactions();
                        } else if (path === '/transactions') {
                            updateTransactionsTable();
                        } else if (path === '/users') {
                            updateUsersTable();
                        } else if (path === '/profit') {
                            updateProfitData();
                        } else if (path.startsWith('/user/')) {
                            updateUserDetail();
                        }
                    }
                });

            // Cập nhật realtime cho từng trang
            if (path === '/users') {
                updateUsersTableRealtime();
            } else if (path === '/') {
                updateDashboardRealtime();
            } else if (path === '/profit') {
                updateProfitDataRealtime();
            }
        }

        // Dashboard realtime
        function updateDashboardRealtime() {
            fetch('/api/stats?_=' + new Date().getTime())
                .then(response => response.json())
                .then(stats => {
                    const statNumbers = document.querySelectorAll('.stat-number');
                    if (statNumbers.length >= 4) {
                        statNumbers[0].textContent = stats.total_users.toLocaleString();
                        statNumbers[1].textContent = stats.new_users.toLocaleString();
                        statNumbers[2].textContent = stats.total_orders.toLocaleString();
                        statNumbers[3].textContent = stats.success_orders.toLocaleString();
                    }
                    const revenueEl = document.querySelector('.stat-number.text-success');
                    if (revenueEl) revenueEl.textContent = stats.revenue.toLocaleString() + 'đ';
                    const costEl = document.querySelector('.stat-number.text-danger');
                    if (costEl) costEl.textContent = stats.cost.toLocaleString() + 'đ';
                    const profitEl = document.querySelector('.profit-number');
                    if (profitEl) profitEl.textContent = stats.profit.toLocaleString() + 'đ';
                });
        }

        // Users table realtime
        function updateUsersTableRealtime() {
            fetch('/api/users/list?_=' + new Date().getTime())
                .then(response => response.json())
                .then(users => {
                    users.forEach(user => {
                        let row = document.querySelector(`tr[data-user-id="${user.user_id}"]`);
                        if (row) {
                            let updated = false;
                            let balanceCell = row.querySelector('.balance-cell');
                            if (balanceCell) {
                                let newBalance = user.balance.toLocaleString() + 'đ';
                                if (balanceCell.textContent !== newBalance) {
                                    balanceCell.textContent = newBalance;
                                    updated = true;
                                }
                            }
                            let rentalsCell = row.querySelector('.rentals-cell');
                            if (rentalsCell) {
                                let newRentals = user.total_rentals;
                                if (rentalsCell.textContent != newRentals) {
                                    rentalsCell.textContent = newRentals;
                                    updated = true;
                                }
                            }
                            let profitCell = row.querySelector('.profit-cell');
                            if (profitCell) {
                                let newProfit = user.profit.toLocaleString() + 'đ';
                                if (profitCell.textContent !== newProfit) {
                                    profitCell.textContent = newProfit;
                                    updated = true;
                                }
                            }
                            if (updated) {
                                row.classList.add('highlight-update');
                                setTimeout(() => row.classList.remove('highlight-update'), 1000);
                            }
                        }
                    });
                });
        }

        // Profit data realtime
        function updateProfitDataRealtime() {
            const period = new URLSearchParams(window.location.search).get('period') || 'today';
            fetch('/api/profit-data?period=' + period + '&_=' + new Date().getTime())
                .then(response => response.json())
                .then(data => {
                    const profitNumbers = document.querySelectorAll('.profit-number');
                    if (profitNumbers.length > 0) {
                        profitNumbers[0].textContent = data.net_profit.toLocaleString() + 'đ';
                    }
                    // Cập nhật bảng dịch vụ nếu có
                    const tbody = document.querySelector('#profitTable tbody');
                    if (tbody && data.by_service) {
                        let html = '';
                        data.by_service.forEach(service => {
                            let marginClass = service.margin >= 30 ? 'success' :
                                            service.margin >= 15 ? 'warning' : 'danger';
                            html += `<tr>
                                <td>${service.name}</td>
                                <td>${service.count}</td>
                                <td>${service.revenue.toLocaleString()}đ</td>
                                <td>${service.cost.toLocaleString()}đ</td>
                                <td class="text-success fw-bold">${service.profit.toLocaleString()}đ</td>
                                <td><span class="badge bg-${marginClass}">${service.margin.toFixed(1)}%</span></td>
                            </tr>`;
                        });
                        tbody.innerHTML = html;
                    }
                });
        }

        // Recent transactions
        function updateRecentTransactions() {
            fetch('/api/recent-transactions?_=' + new Date().getTime())
                .then(response => response.json())
                .then(transactions => {
                    const tbody = document.querySelector('.table-hover tbody');
                    if (!tbody) return;
                    let html = '';
                    transactions.forEach(t => {
                        html += `<tr>
                            <td>${t.time}</td>
                            <td><code>${t.user_id}</code></td>
                            <td><span class="badge bg-${t.type === 'Nạp tiền' ? 'success' : 'primary'}">${t.type}</span></td>
                            <td>${t.service || '—'}</td>
                            <td class="fw-bold">${t.amount.toLocaleString()}đ</td>
                            <td class="text-success fw-bold">${t.profit.toLocaleString()}đ</td>
                            <td><span class="status-success">Thành công</span></td>
                        </tr>`;
                    });
                    tbody.innerHTML = html;
                });
        }

        // Transactions table
        function updateTransactionsTable() {
            const tab = new URLSearchParams(window.location.search).get('tab') || 'all';
            fetch('/api/transactions?tab=' + tab + '&_=' + new Date().getTime())
                .then(response => response.json())
                .then(transactions => {
                    const tbody = document.querySelector('#transTable tbody');
                    if (!tbody) return;
                    let html = '';
                    transactions.forEach(t => {
                        let statusClass = t.status === 'success' ? 'success' :
                                        t.status === 'pending' ? 'warning' : 'danger';
                        let statusText = t.status === 'success' ? 'Thành công' :
                                        t.status === 'pending' ? 'Đang xử lý' : 'Đã hủy';
                        html += `<tr>
                            <td>${t.time}</td>
                            <td><code>${t.user_id}</code></td>
                            <td><span class="badge bg-${t.type === 'deposit' ? 'success' : t.type === 'rental' ? 'primary' : 'warning'}">${t.type_display}</span></td>
                            <td>${t.service || '—'}</td>
                            <td class="fw-bold ${t.type === 'deposit' ? 'text-success' : 'text-danger'}">${t.amount.toLocaleString()}đ</td>
                            <td class="text-success">${t.profit.toLocaleString()}đ</td>
                            <td><code>${t.code}</code></td>
                            <td><span class="status-${statusClass}">${statusText}</span></td>
                        </tr>`;
                    });
                    tbody.innerHTML = html;
                });
        }

        // User detail realtime
        function updateUserDetail() {
            const userId = window.location.pathname.split('/').pop();
            fetch('/api/user/' + userId + '?_=' + new Date().getTime())
                .then(response => response.json())
                .then(data => {
                    if (data.error) return;
                    const rentalsTbody = document.querySelector('#rentalsTab tbody');
                    if (rentalsTbody) {
                        let html = '';
                        data.rentals.forEach(r => {
                            html += `<tr>
                                <td>${r.created_at}</td>
                                <td>${r.service_name}</td>
                                <td><code>${r.phone_number || '—'}</code></td>
                                <td class="fw-bold">${r.price_charged.toLocaleString()}đ</td>
                                <td class="text-danger">${r.cost.toLocaleString()}đ</td>
                                <td class="text-success fw-bold">${r.profit.toLocaleString()}đ</td>
                                <td><span class="badge bg-${r.status === 'success' ? 'success' : r.status === 'waiting' ? 'warning' : r.status === 'cancelled' ? 'danger' : 'secondary'}">${r.status_display}</span></td>
                            </tr>`;
                        });
                        rentalsTbody.innerHTML = html;
                    }
                });
        }

        // Hiển thị thông báo
        function showNotification(message, type = 'info') {
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert alert-${type} alert-dismissible fade show flash-message`;
            alertDiv.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(alertDiv);
            setTimeout(() => alertDiv.remove(), 3000);
        }

        // Hàm tổng hợp cập nhật theo trang
        function updateData() {
            const path = window.location.pathname;
            updateRealtimeData(); // Luôn chạy
        }

        // Chạy realtime mỗi 1 giây
        setInterval(updateData, 1000);
        document.addEventListener('DOMContentLoaded', function() {
            updateData();
        });

        // ==================== MODAL HANDLING ====================
        function toggleAll() {
            let checkboxes = document.querySelectorAll('.user-checkbox');
            let selectAll = document.getElementById('selectAll');
            checkboxes.forEach(cb => {
                cb.checked = selectAll.checked;
                if (cb.checked) {
                    if (!selectedUsers.includes(cb.value)) {
                        selectedUsers.push(cb.value);
                    }
                } else {
                    selectedUsers = selectedUsers.filter(id => id !== cb.value);
                }
            });
            updateSelectedCount();
        }

        function updateSelectedCount() {
            const countSpan = document.getElementById('selectedCount');
            if (countSpan) countSpan.innerText = `Đã chọn ${selectedUsers.length} user`;
        }

        document.querySelectorAll('.user-checkbox').forEach(cb => {
            cb.addEventListener('change', function() {
                if (this.checked) {
                    if (!selectedUsers.includes(this.value)) {
                        selectedUsers.push(this.value);
                    }
                } else {
                    selectedUsers = selectedUsers.filter(id => id !== this.value);
                    document.getElementById('selectAll').checked = false;
                }
                updateSelectedCount();
            });
        });

        function addMoney(userId) {
            document.getElementById('modal_user_id').value = userId;
            new bootstrap.Modal(document.getElementById('addMoneyModal')).show();
        }

        function deductMoney(userId) {
            document.getElementById('deduct_modal_user_id').value = userId;
            new bootstrap.Modal(document.getElementById('deductMoneyModal')).show();
        }

        function sendMessage(userId) {
            document.getElementById('msg_user_id').value = userId;
            document.getElementById('msg_target_type').value = 'single';
            document.getElementById('selectedUsersInfo').classList.add('d-none');
            new bootstrap.Modal(document.getElementById('sendMessageModal')).show();
        }

        function sendToSelected() {
            if (selectedUsers.length === 0) {
                alert('Vui lòng chọn ít nhất 1 user!');
                return;
            }
            document.getElementById('msg_target_type').value = 'multiple';
            document.getElementById('selectedUsersInfo').classList.remove('d-none');
            document.getElementById('selectedUsersCount').innerText = selectedUsers.length;
            new bootstrap.Modal(document.getElementById('sendMessageModal')).show();
        }

        function broadcastToAll() {
            if (!confirm('Bạn có chắc muốn gửi tin nhắn cho TẤT CẢ user?')) return;
            document.getElementById('msg_target_type').value = 'all';
            document.getElementById('selectedUsersInfo').classList.remove('d-none');
            document.getElementById('selectedUsersCount').innerText = 'tất cả';
            new bootstrap.Modal(document.getElementById('sendMessageModal')).show();
        }

        function toggleBan(userId) {
            if(confirm('Bạn chắc chắn muốn thay đổi trạng thái khóa user này?')) {
                fetch('/toggle_ban', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId})
                }).then(() => location.reload());
            }
        }

        function exportToExcel() {
            window.location.href = '/export_users';
        }

        // Xem chi tiết số thuê của user (modal)
        function viewUserRentals(userId, username) {
            currentUserId = userId;
            document.getElementById('modalUserName').innerText = username || 'User ' + userId;
            document.getElementById('modalUserId').innerText = userId;
            const modal = new bootstrap.Modal(document.getElementById('userRentalsModal'));
            modal.show();
            loadUserRentals(userId);
            startRealtimeUpdates();
            const modalElement = document.getElementById('userRentalsModal');
            modalElement.removeEventListener('hidden.bs.modal', handleModalClose);
            modalElement.addEventListener('hidden.bs.modal', handleModalClose);
        }

        function handleModalClose() {
            if (realtimeInterval) {
                clearInterval(realtimeInterval);
                realtimeInterval = null;
            }
        }

        let realtimeInterval = null;
        function startRealtimeUpdates() {
            if (realtimeInterval) clearInterval(realtimeInterval);
            realtimeInterval = setInterval(() => {
                if (document.getElementById('userRentalsModal').classList.contains('show') && currentUserId) {
                    const now = new Date().getTime();
                    const last = lastUpdateTime[currentUserId] || 0;
                    if (now - last >= 1000) {
                        loadUserRentals(currentUserId);
                    }
                }
            }, 1000);
        }

        function loadUserRentals(userId, page = 1) {
            const tbody = document.getElementById('modalRentalsBody');
            const timestamp = new Date().getTime();
            if (page === 1) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center"><div class="spinner-border text-primary"></div></td></tr>';
            }
            fetch('/api/user-recent-rentals/' + userId + '?page=' + page + '&_=' + timestamp)
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">${data.error}</td></tr>`;
                        return;
                    }
                    document.getElementById('modalTotalRentals').innerText = data.total_rentals || 0;
                    if (!data.recent_rentals || data.recent_rentals.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Chưa có số thuê nào</td></tr>';
                        return;
                    }
                    let html = '';
                    data.recent_rentals.forEach(r => {
                        let statusClass = 'warning';
                        let statusText = '⏳ Chờ OTP';
                        let timeDisplay = r.expires_at || '—';
                        let actions = '';
                        if (r.status === 'waiting') {
                            if (r.time_left) {
                                timeDisplay = `<span class="text-warning">${r.time_left}</span>`;
                                actions = `<button class="btn btn-sm btn-primary" onclick="checkOTP('${r.otp_id}', ${r.id})"><i class="bi bi-search"></i></button>`;
                            } else {
                                timeDisplay = '<span class="text-danger">Hết hạn</span>';
                            }
                            statusText = '⏳ Đang chờ';
                        } else if (r.status === 'success' || r.status === 'completed') {
                            statusClass = 'success';
                            statusText = '✅ Thành công';
                        } else if (r.status === 'cancelled') {
                            statusClass = 'danger';
                            statusText = '❌ Đã hủy';
                        } else if (r.status === 'expired') {
                            statusClass = 'secondary';
                            statusText = '⏰ Hết hạn';
                        }
                        let otpDisplay = r.otp ? `<code class="otp-code">${r.otp}</code>` : '—';
                        if (r.otp && r.otp.includes('Audio')) {
                            otpDisplay = '<span class="badge bg-info">🔊 Audio OTP</span>';
                        }
                        let rowClass = (r.otp && r.status === 'success') ? 'table-success highlight-update' : '';
                        html += `<tr class="${rowClass}" data-rental-id="${r.id}">
                            <td><small>${r.created_at}</small></td>
                            <td><code class="phone-number">${r.phone}</code></td>
                            <td>${r.service}</td>
                            <td class="fw-bold text-danger">${r.price.toLocaleString()}đ</td>
                            <td class="otp-cell">${otpDisplay}</td>
                            <td><span class="badge bg-${statusClass} status-badge">${statusText}</span></td>
                            <td><small class="time-cell">${timeDisplay}</small></td>
                            <td>${actions}</td>
                        </tr>`;
                    });
                    tbody.innerHTML = html;
                    if (data.total_pages > 1) {
                        let pagination = '<tr><td colspan="8" class="text-center"><nav><ul class="pagination justify-content-center">';
                        for (let i = 1; i <= data.total_pages; i++) {
                            pagination += `<li class="page-item ${i === page ? 'active' : ''}"><a class="page-link" href="#" onclick="loadUserRentals(${userId}, ${i}); return false;">${i}</a></li>`;
                        }
                        pagination += '</ul></nav></td></tr>';
                        tbody.innerHTML += pagination;
                    }
                    lastUpdateTime[userId] = timestamp;
                })
                .catch(error => {
                    if (page === 1) tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Lỗi kết nối</td></tr>';
                });
        }

        function checkOTP(otpId, rentalId) {
            fetch('/api/check-otp/' + otpId + '/' + rentalId, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification('✅ OTP: ' + data.otp, 'success');
                        loadUserRentals(currentUserId);
                    } else {
                        showNotification('❌ ' + (data.error || 'Không tìm thấy OTP'), 'danger');
                    }
                })
                .catch(() => showNotification('❌ Lỗi kết nối', 'danger'));
        }

        function refreshUserRentals() {
            if (currentUserId) {
                loadUserRentals(currentUserId);
                showNotification('🔄 Đang làm mới dữ liệu...', 'info');
            }
        }

        // Xử lý form
        document.getElementById('addMoneyForm')?.addEventListener('submit', function(e) {
            e.preventDefault();
            fetch('/add_money', {
                method: 'POST',
                body: new URLSearchParams(new FormData(this))
            }).then(response => response.json()).then(data => {
                if (data.success) location.reload();
                else alert('Lỗi: ' + data.error);
            }).catch(error => alert('Lỗi kết nối: ' + error));
        });

        document.getElementById('deductMoneyForm')?.addEventListener('submit', function(e) {
            e.preventDefault();
            fetch('/deduct_money', {
                method: 'POST',
                body: new URLSearchParams(new FormData(this))
            }).then(response => response.json()).then(data => {
                if (data.success) location.reload();
                else alert('Lỗi: ' + data.error);
            }).catch(error => alert('Lỗi kết nối: ' + error));
        });

        document.getElementById('sendMessageForm')?.addEventListener('submit', function(e) {
            e.preventDefault();
            let formData = new FormData(this);
            let targetType = document.getElementById('msg_target_type').value;
            if (targetType === 'multiple') {
                formData.append('user_ids', JSON.stringify(selectedUsers));
            }
            fetch('/send_message', {
                method: 'POST',
                body: formData
            }).then(response => response.json()).then(data => {
                if (data.success) {
                    alert(`✅ Gửi thành công!\n• Thành công: ${data.success_count}\n• Thất bại: ${data.failed_count}`);
                    bootstrap.Modal.getInstance(document.getElementById('sendMessageModal')).hide();
                } else {
                    alert('Lỗi: ' + data.error);
                }
            }).catch(error => alert('Lỗi kết nối: ' + error));
        });

        // Tìm kiếm trên bảng users
        document.getElementById('searchInput')?.addEventListener('keyup', function() {
            let val = this.value.toLowerCase();
            document.querySelectorAll('#usersTable tbody tr').forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(val) ? '' : 'none';
            });
        });

        // Preview tin nhắn
        window.updatePreview = function() {
            let message = document.getElementById('message').value;
            let preview = document.getElementById('messagePreview');
            if (preview) {
                preview.innerHTML = message ? message.replace(/\\n/g, '<br>') : '<span class="text-muted">Nhập nội dung tin nhắn...</span>';
            }
        };
    </script>
</body>
</html>
'''

# ====================== CÁC TEMPLATE CON (VIỆT HÓA) ======================
INDEX_TEMPLATE = '''
<div class="row g-4">
    <div class="col-12">
        <div class="card">
            <div class="card-header"><h5><i class="bi bi-calendar3"></i> Thống kê tổng quan</h5></div>
            <div class="card-body">
                <div class="row g-4">
                    <div class="col-md-3"><div class="stat-card"><i class="bi bi-people-fill" style="font-size:48px;color:#6366f1"></i><div class="stat-number">{{ "{:,.0f}".format(stats.total_users) }}</div><div class="text-muted mt-2">Tổng người dùng</div></div></div>
                    <div class="col-md-3"><div class="stat-card"><i class="bi bi-person-plus-fill" style="font-size:48px;color:#10b981"></i><div class="stat-number">{{ "{:,.0f}".format(stats.new_users) }}</div><div class="text-muted mt-2">Người dùng mới (24h)</div></div></div>
                    <div class="col-md-3"><div class="stat-card"><i class="bi bi-cart-check-fill" style="font-size:48px;color:#f59e0b"></i><div class="stat-number">{{ "{:,.0f}".format(stats.total_orders) }}</div><div class="text-muted mt-2">Tổng số thuê</div></div></div>
                    <div class="col-md-3"><div class="stat-card"><i class="bi bi-check-circle-fill" style="font-size:48px;color:#10b981"></i><div class="stat-number">{{ "{:,.0f}".format(stats.success_orders) }}</div><div class="text-muted mt-2">Thành công</div></div></div>
                </div>
                <div class="row mt-5 g-4">
                    <div class="col-md-4">
                        <div class="card h-100">
                            <div class="card-header"><h5>Doanh thu</h5></div>
                            <div class="card-body text-center">
                                <div class="stat-number text-success">{{ "{:,.0f}".format(stats.revenue) }}đ</div>
                                <p class="text-muted">Tổng doanh thu (nạp QR + thuê số)</p>
                                <div class="row text-start mt-3">
                                    <div class="col-6"><strong>Nạp QR</strong><br><span class="text-success">{{ "{:,.0f}".format(stats.qr_deposit) }}đ</span></div>
                                    <div class="col-6"><strong>Thuê số</strong><br><span class="text-primary">{{ "{:,.0f}".format(stats.rental) }}đ</span></div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card h-100">
                            <div class="card-header"><h5>Chi phí</h5></div>
                            <div class="card-body text-center">
                                <div class="stat-number text-danger">{{ "{:,.0f}".format(stats.cost) }}đ</div>
                                <p class="text-muted">Tổng chi phí API</p>
                                <div class="mt-3"><strong>Biên lợi nhuận:</strong> <span class="badge bg-{{ 'success' if stats.profit_margin >= 30 else 'warning' if stats.profit_margin >= 15 else 'danger' }}">{{ "{:.1f}".format(stats.profit_margin) }}%</span></div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card h-100">
                            <div class="card-header"><h5>Lợi nhuận ròng</h5></div>
                            <div class="card-body text-center">
                                <div class="{{ 'profit-number' if stats.profit >= 0 else 'text-danger' }}">{{ "{:,.0f}".format(stats.profit) }}đ</div>
                                <p class="text-muted">Sau khi trừ chi phí (chỉ tính nạp QR)</p>
                                <small class="text-muted">(Không tính cộng thủ công: {{ "{:,.0f}".format(stats.manual_deposit) }}đ)</small>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
<div class="card mt-4">
    <div class="card-header"><h5><i class="bi bi-clock-history"></i> Giao dịch gần đây (10 giao dịch mới nhất)</h5></div>
    <div class="card-body p-0">
        <table class="table table-hover mb-0 datatable">
            <thead><tr><th>Thời gian</th><th>User ID</th><th>Loại</th><th>Dịch vụ</th><th>Số tiền</th><th>Lợi nhuận</th><th>Trạng thái</th></tr></thead>
            <tbody>
                {% for trans in stats.recent_transactions %}
                <tr>
                    <td>{{ trans.time }}</td>
                    <td><code>{{ trans.user_id }}</code></td>
                    <td><span class="badge bg-{{ 'success' if trans.type == 'Nạp tiền' else 'primary' }}">{{ trans.type }}</span></td>
                    <td>{{ trans.service or '—' }}</td>
                    <td class="fw-bold">{{ "{:,.0f}".format(trans.amount) }}đ</td>
                    <td class="text-success fw-bold">{{ "{:,.0f}".format(trans.profit) }}đ</td>
                    <td><span class="status-success">Thành công</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

USERS_TEMPLATE = '''
<div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
        <h5><i class="bi bi-people-fill"></i> Quản lý người dùng</h5>
        <div>
            <button class="btn btn-info text-white me-2" onclick="broadcastToAll()"><i class="bi bi-megaphone-fill"></i> Gửi tin cho tất cả</button>
            <button class="btn btn-success" onclick="exportToExcel()"><i class="bi bi-file-earmark-excel"></i> Xuất Excel</button>
        </div>
    </div>
    <div class="card-body">
        <input type="text" id="searchInput" class="search-box mb-4 w-100" placeholder="🔍 Tìm kiếm User ID, Username, Số dư...">
        <table id="usersTable" class="table table-striped table-hover datatable">
            <thead>
                <tr>
                    <th><input type="checkbox" id="selectAll" onclick="toggleAll()"></th>
                    <th>ID</th>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Số dư</th>
                    <th>Đã thuê</th>
                    <th>Tổng chi</th>
                    <th>Lợi nhuận</th>
                    <th>Ngày tạo</th>
                    <th>Trạng thái</th>
                    <th>Thao tác</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr data-user-id="{{ user.user_id }}">
                    <td><input type="checkbox" class="user-checkbox" value="{{ user.user_id }}"></td>
                    <td>{{ user.id }}</td>
                    <td><code>{{ user.user_id }}</code></td>
                    <td>@{{ user.username or 'N/A' }}</td>
                    <td class="fw-bold text-success balance-cell">{{ "{:,.0f}".format(user.balance) }}đ</td>
                    <td class="rentals-cell">{{ user.total_rentals }}</td>
                    <td>{{ "{:,.0f}".format(user.total_spent) }}đ</td>
                    <td class="text-success fw-bold profit-cell">{{ "{:,.0f}".format(user.profit or 0) }}đ</td>
                    <td>{{ user.created_at }}</td>
                    <td><span class="badge bg-{{ 'danger' if user.is_banned else 'success' }}">{{ 'Bị khóa' if user.is_banned else 'Hoạt động' }}</span></td>
                    <td>
                        <button class="btn btn-sm btn-primary" onclick="addMoney({{ user.user_id }})"><i class="bi bi-plus-circle"></i></button>
                        <button class="btn btn-sm btn-warning" onclick="deductMoney({{ user.user_id }})"><i class="bi bi-dash-circle"></i></button>
                        <button class="btn btn-sm btn-info text-white" onclick="sendMessage({{ user.user_id }})"><i class="bi bi-chat"></i></button>
                        <button class="btn btn-sm btn-{{ 'success' if user.is_banned else 'danger' }}" onclick="toggleBan({{ user.user_id }})"><i class="bi bi-{{ 'unlock' if user.is_banned else 'lock' }}"></i></button>
                        <a href="/user/{{ user.user_id }}" class="btn btn-sm btn-info text-white"><i class="bi bi-eye-fill"></i></a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <div class="mt-3">
            <button class="btn btn-info" onclick="sendToSelected()"><i class="bi bi-send"></i> Gửi tin cho user đã chọn</button>
            <span id="selectedCount" class="ms-3 text-muted">Đã chọn 0 user</span>
        </div>
    </div>
</div>

<!-- Modal Cộng tiền -->
<div class="modal fade" id="addMoneyModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header bg-success text-white">
                <h5 class="modal-title"><i class="bi bi-plus-circle-fill"></i> Cộng tiền thủ công</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <form id="addMoneyForm">
                <div class="modal-body">
                    <input type="hidden" name="user_id" id="modal_user_id">
                    <div class="mb-3">
                        <label class="form-label fw-bold">Số tiền (VNĐ)</label>
                        <input type="number" class="form-control form-control-lg" name="amount" min="1000" step="1000" required placeholder="Nhập số tiền">
                    </div>
                    <div class="mb-3">
                        <label class="form-label fw-bold">Lý do</label>
                        <input type="text" class="form-control" name="reason" value="Cộng tiền thủ công">
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="submit" class="btn btn-success">Xác nhận cộng tiền</button>
                </div>
            </form>
        </div>
    </div>
</div>

<!-- Modal Trừ tiền -->
<div class="modal fade" id="deductMoneyModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header bg-warning text-dark">
                <h5 class="modal-title"><i class="bi bi-dash-circle-fill"></i> Trừ tiền thủ công</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <form id="deductMoneyForm">
                <div class="modal-body">
                    <input type="hidden" name="user_id" id="deduct_modal_user_id">
                    <div class="mb-3">
                        <label class="form-label fw-bold">Số tiền (VNĐ)</label>
                        <input type="number" class="form-control form-control-lg" name="amount" min="1000" step="1000" required placeholder="Nhập số tiền">
                    </div>
                    <div class="mb-3">
                        <label class="form-label fw-bold">Lý do</label>
                        <input type="text" class="form-control" name="reason" value="Trừ tiền thủ công">
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="submit" class="btn btn-warning">Xác nhận trừ tiền</button>
                </div>
            </form>
        </div>
    </div>
</div>

<!-- Modal Gửi tin nhắn -->
<div class="modal fade" id="sendMessageModal" tabindex="-1">
    <div class="modal-dialog modal-lg modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header bg-info text-white">
                <h5 class="modal-title"><i class="bi bi-chat-dots-fill"></i> Gửi tin nhắn</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <form id="sendMessageForm">
                <div class="modal-body">
                    <input type="hidden" name="user_id" id="msg_user_id">
                    <input type="hidden" name="target_type" id="msg_target_type" value="single">
                    <div id="selectedUsersInfo" class="alert alert-info d-none">
                        <strong><span id="selectedUsersCount">0</span> user được chọn</strong>
                    </div>
                    <div class="mb-3">
                        <label class="form-label fw-bold">Nội dung tin nhắn</label>
                        <textarea class="form-control" name="message" id="message" rows="5" required placeholder="Nhập nội dung tin nhắn..." onkeyup="updatePreview()"></textarea>
                        <div class="form-text">Hỗ trợ Markdown: *in đậm*, `mã`, [link](url)</div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label fw-bold">Xem trước</label>
                        <div class="message-preview" id="messagePreview">
                            <span class="text-muted">Nhập nội dung tin nhắn...</span>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="submit" class="btn btn-info text-white"><i class="bi bi-send"></i> Gửi tin nhắn</button>
                </div>
            </form>
        </div>
    </div>
</div>

<!-- Modal chi tiết số thuê của user -->
<div class="modal fade" id="userRentalsModal" tabindex="-1" data-bs-backdrop="static">
    <div class="modal-dialog modal-xl modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header bg-primary text-white">
                <h5 class="modal-title"><i class="bi bi-phone"></i> 100 Số Thuê Gần Nhất - <span id="modalUserName"></span></h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <div class="row mb-3">
                    <div class="col-md-6"><strong>User ID:</strong> <code id="modalUserId"></code></div>
                    <div class="col-md-6"><strong>Tổng số thuê:</strong> <span id="modalTotalRentals" class="badge bg-primary"></span></div>
                </div>
                <div class="table-responsive">
                    <table class="table table-striped table-hover" id="modalRentalsTable">
                        <thead><tr><th>Thời gian</th><th>Số điện thoại</th><th>Dịch vụ</th><th>Giá thuê</th><th>OTP</th><th>Trạng thái</th><th>Hết hạn</th><th>Thao tác</th></tr></thead>
                        <tbody id="modalRentalsBody"><tr><td colspan="8" class="text-center"><div class="spinner-border text-primary"></div></td></tr></tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
                <button type="button" class="btn btn-primary" onclick="refreshUserRentals()"><i class="bi bi-arrow-repeat"></i> Làm mới</button>
            </div>
        </div>
    </div>
</div>
'''

PROFIT_TEMPLATE = '''
<div class="card">
    <div class="card-header"><h5><i class="bi bi-graph-up-arrow"></i> Báo cáo lợi nhuận</h5></div>
    <div class="card-body">
        <ul class="nav nav-tabs mb-4">
            <li class="nav-item"><a class="nav-link {% if period == 'today' %}active{% endif %}" href="?period=today">Hôm nay</a></li>
            <li class="nav-item"><a class="nav-link {% if period == 'week' %}active{% endif %}" href="?period=week">Tuần này</a></li>
            <li class="nav-item"><a class="nav-link {% if period == 'month' %}active{% endif %}" href="?period=month">Tháng này</a></li>
            <li class="nav-item"><a class="nav-link {% if period == 'all' %}active{% endif %}" href="?period=all">Tất cả thời gian</a></li>
        </ul>
        <div class="row g-4 text-center">
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ "{:,.0f}".format(profit.total_revenue) }}đ</div><div class="text-muted">Tổng doanh thu</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number text-danger">{{ "{:,.0f}".format(profit.total_cost) }}đ</div><div class="text-muted">Tổng chi phí</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="profit-number">{{ "{:,.0f}".format(profit.net_profit) }}đ</div><div class="text-muted">Lợi nhuận ròng</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ "{:.1f}".format(profit.profit_margin) }}%</div><div class="text-muted">Biên lợi nhuận</div></div></div>
        </div>
    </div>
</div>
<div class="card mt-4">
    <div class="card-header"><h5>Lợi nhuận chi tiết theo dịch vụ</h5></div>
    <div class="card-body">
        <table id="profitTable" class="table table-striped datatable">
            <thead><tr><th>Dịch vụ</th><th>Lượt thuê</th><th>Doanh thu</th><th>Chi phí</th><th>Lợi nhuận</th><th>Biên LN</th></tr></thead>
            <tbody>
                {% for service in profit.by_service %}
                <tr>
                    <td>{{ service.name }}</td>
                    <td>{{ service.count }}</td>
                    <td>{{ "{:,.0f}".format(service.revenue) }}đ</td>
                    <td>{{ "{:,.0f}".format(service.cost) }}đ</td>
                    <td class="text-success fw-bold">{{ "{:,.0f}".format(service.profit) }}đ</td>
                    <td><span class="badge bg-{{ 'success' if service.margin >= 30 else 'warning' if service.margin >= 15 else 'danger' }}">{{ "{:.1f}".format(service.margin) }}%</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

TRANSACTIONS_TEMPLATE = '''
<div class="card">
    <div class="card-header"><h5><i class="bi bi-cash-stack"></i> Lịch sử giao dịch toàn bộ</h5></div>
    <div class="card-body">
        <ul class="nav nav-tabs mb-3">
            <li class="nav-item"><a class="nav-link {% if tab == 'all' %}active{% endif %}" href="?tab=all">Tất cả</a></li>
            <li class="nav-item"><a class="nav-link {% if tab == 'deposit' %}active{% endif %}" href="?tab=deposit">Nạp tiền</a></li>
            <li class="nav-item"><a class="nav-link {% if tab == 'rental' %}active{% endif %}" href="?tab=rental">Thuê số</a></li>
            <li class="nav-item"><a class="nav-link {% if tab == 'deduct' %}active{% endif %}" href="?tab=deduct">Trừ tiền</a></li>
        </ul>
        <table id="transTable" class="table table-striped datatable">
            <thead><tr><th>Thời gian</th><th>User ID</th><th>Loại</th><th>Dịch vụ</th><th>Số tiền</th><th>Lợi nhuận</th><th>Mã GD</th><th>Trạng thái</th></tr></thead>
            <tbody>
                {% for trans in transactions %}
                <tr>
                    <td>{{ trans.time }}</td>
                    <td><code>{{ trans.user_id }}</code></td>
                    <td><span class="badge bg-{{ 'success' if trans.type == 'deposit' else 'primary' if trans.type == 'rental' else 'warning' }}">{{ trans.type_display }}</span></td>
                    <td>{{ trans.service or '—' }}</td>
                    <td class="fw-bold {{ 'text-success' if trans.type == 'deposit' else 'text-danger' }}">{{ "{:,.0f}".format(trans.amount) }}đ</td>
                    <td class="text-success">{{ "{:,.0f}".format(trans.profit) }}đ</td>
                    <td><code>{{ trans.code }}</code></td>
                    <td><span class="status-{{ 'success' if trans.status == 'success' else 'cancel' }}">{{ 'Thành công' if trans.status == 'success' else 'Đã hủy' }}</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

MANUAL_TEMPLATE = '''
<div class="row">
    <div class="col-lg-6">
        <div class="card">
            <div class="card-header bg-success text-white"><h5><i class="bi bi-plus-circle-fill"></i> Cộng tiền thủ công</h5></div>
            <div class="card-body">
                <form method="POST" action="/add_money">
                    <div class="mb-3">
                        <label class="form-label">User ID (Telegram ID)</label>
                        <input type="number" class="form-control" name="user_id" required placeholder="5180190297">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Số tiền (VNĐ)</label>
                        <input type="number" class="form-control" name="amount" min="1000" step="1000" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Lý do cộng tiền</label>
                        <input type="text" class="form-control" name="reason" value="Cộng tiền thủ công">
                    </div>
                    <button type="submit" class="btn btn-success w-100 py-2"><i class="bi bi-check-circle"></i> Xác nhận cộng tiền</button>
                </form>
            </div>
        </div>
    </div>
    <div class="col-lg-6">
        <div class="card">
            <div class="card-header bg-warning"><h5><i class="bi bi-dash-circle-fill"></i> Trừ tiền thủ công</h5></div>
            <div class="card-body">
                <form method="POST" action="/deduct_money">
                    <div class="mb-3">
                        <label class="form-label">User ID (Telegram ID)</label>
                        <input type="number" class="form-control" name="user_id" required placeholder="5180190297">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Số tiền (VNĐ)</label>
                        <input type="number" class="form-control" name="amount" min="1000" step="1000" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Lý do trừ tiền</label>
                        <input type="text" class="form-control" name="reason" value="Trừ tiền thủ công">
                    </div>
                    <button type="submit" class="btn btn-warning w-100 py-2"><i class="bi bi-check-circle"></i> Xác nhận trừ tiền</button>
                </form>
            </div>
        </div>
    </div>
</div>
<div class="card mt-4">
    <div class="card-header"><h5>Lịch sử cộng/trừ thủ công gần đây</h5></div>
    <div class="card-body">
        <table class="table datatable">
            <thead><tr><th>Thời gian</th><th>User ID</th><th>Loại</th><th>Số tiền</th><th>Lý do</th></tr></thead>
            <tbody>
                {% for trans in manual_trans %}
                <tr>
                    <td>{{ trans.time }}</td>
                    <td><code>{{ trans.user_id }}</code></td>
                    <td><span class="badge bg-{{ 'success' if trans.type == 'Cộng' else 'warning' }}">{{ trans.type }}</span></td>
                    <td class="{{ 'text-success' if trans.type == 'Cộng' else 'text-danger' }} fw-bold">{{ "{:,.0f}".format(trans.amount) }}đ</td>
                    <td>{{ trans.reason }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

BROADCAST_TEMPLATE = '''
<div class="row">
    <div class="col-lg-8 mx-auto">
        <div class="card">
            <div class="card-header bg-info text-white">
                <h5><i class="bi bi-megaphone-fill"></i> Gửi thông báo hàng loạt</h5>
            </div>
            <div class="card-body">
                <ul class="nav nav-tabs mb-4">
                    <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#single">Gửi cho 1 user</a></li>
                    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#multiple">Gửi cho nhiều user</a></li>
                    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#all">Gửi cho tất cả</a></li>
                </ul>
                <div class="tab-content">
                    <div class="tab-pane fade show active" id="single">
                        <form method="POST" action="/send_message" onsubmit="return confirm('Gửi tin nhắn này?')">
                            <div class="mb-3">
                                <label class="form-label fw-bold">User ID</label>
                                <input type="number" class="form-control" name="user_id" required placeholder="5180190297">
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-bold">Nội dung tin nhắn</label>
                                <textarea class="form-control" name="message" rows="5" required placeholder="Nhập nội dung..."></textarea>
                            </div>
                            <button type="submit" class="btn btn-info text-white w-100 py-2"><i class="bi bi-send"></i> Gửi tin nhắn</button>
                        </form>
                    </div>
                    <div class="tab-pane fade" id="multiple">
                        <form method="POST" action="/send_message_bulk" onsubmit="return confirm('Gửi tin nhắn cho các user đã chọn?')">
                            <div class="mb-3">
                                <label class="form-label fw-bold">Danh sách User ID (mỗi dòng 1 ID)</label>
                                <textarea class="form-control" name="user_ids" rows="5" required placeholder="5180190297&#10;6340003618&#10;8627082826"></textarea>
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-bold">Nội dung tin nhắn</label>
                                <textarea class="form-control" name="message" rows="5" required placeholder="Nhập nội dung..."></textarea>
                            </div>
                            <button type="submit" class="btn btn-info text-white w-100 py-2"><i class="bi bi-send"></i> Gửi tin nhắn</button>
                        </form>
                    </div>
                    <div class="tab-pane fade" id="all">
                        <form method="POST" action="/send_message_all" onsubmit="return confirm('⚠️ Bạn có chắc muốn gửi tin nhắn cho TẤT CẢ user?\\nSố lượng: {{ total_users }} user')">
                            <div class="mb-3">
                                <label class="form-label fw-bold">Nội dung tin nhắn</label>
                                <textarea class="form-control" name="message" rows="5" required placeholder="Nhập nội dung..."></textarea>
                                <div class="form-text">Tin nhắn sẽ được gửi đến {{ total_users }} user</div>
                            </div>
                            <button type="submit" class="btn btn-info text-white w-100 py-2"><i class="bi bi-send"></i> Gửi cho tất cả ({{ total_users }} user)</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
<div class="card mt-4">
    <div class="card-header"><h5>Lịch sử gửi tin gần đây</h5></div>
    <div class="card-body">
        <table class="table datatable">
            <thead><tr><th>Thời gian</th><th>Người gửi</th><th>Số user</th><th>Nội dung</th></tr></thead>
            <tbody>
                {% for log in broadcast_logs %}
                <tr>
                    <td>{{ log.time }}</td>
                    <td>Admin</td>
                    <td>{{ log.count }}</td>
                    <td>{{ log.message[:50] }}...</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

STATISTICS_TEMPLATE = '''
<div class="card">
    <div class="card-header"><h5><i class="bi bi-bar-chart-line"></i> Thống kê chi tiết theo thời gian</h5></div>
    <div class="card-body">
        <ul class="nav nav-tabs mb-3">
            <li class="nav-item"><a class="nav-link {% if stat_type == 'daily' %}active{% endif %}" href="?type=daily">Theo ngày</a></li>
            <li class="nav-item"><a class="nav-link {% if stat_type == 'weekly' %}active{% endif %}" href="?type=weekly">Theo tuần</a></li>
            <li class="nav-item"><a class="nav-link {% if stat_type == 'monthly' %}active{% endif %}" href="?type=monthly">Theo tháng</a></li>
        </ul>
        <table class="table table-striped datatable">
            <thead><tr><th>Thời gian</th><th>Nạp tiền</th><th>Thuê số</th><th>Chi phí</th><th>Lợi nhuận</th><th>Tổng GD</th></tr></thead>
            <tbody>
                {% for stat in stats_data %}
                <tr>
                    <td>{{ stat.period }}</td>
                    <td>{{ "{:,.0f}".format(stat.deposit) }}đ</td>
                    <td>{{ "{:,.0f}".format(stat.rental) }}đ</td>
                    <td>{{ "{:,.0f}".format(stat.cost) }}đ</td>
                    <td class="text-success fw-bold">{{ "{:,.0f}".format(stat.profit) }}đ</td>
                    <td>{{ stat.count }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

USER_DETAIL_TEMPLATE = '''
<div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
        <h5><i class="bi bi-person-fill"></i> CHI TIẾT USER #{{ user.user_id }}</h5>
        <div>
            <button class="btn btn-info text-white btn-sm me-2" onclick="sendMessage({{ user.user_id }})"><i class="bi bi-chat"></i> Nhắn tin</button>
            <button class="btn btn-success btn-sm me-2" onclick="addMoney({{ user.user_id }})"><i class="bi bi-plus-circle"></i> Cộng tiền</button>
            <button class="btn btn-warning btn-sm me-2" onclick="deductMoney({{ user.user_id }})"><i class="bi bi-dash-circle"></i> Trừ tiền</button>
            <a href="/users" class="btn btn-secondary btn-sm"><i class="bi bi-arrow-left"></i> Quay lại</a>
        </div>
    </div>
    <div class="card-body">
        <div class="row">
            <div class="col-md-4">
                <div class="card h-100">
                    <div class="card-header bg-primary text-white"><h6 class="mb-0"><i class="bi bi-info-circle"></i> Thông tin cơ bản</h6></div>
                    <div class="card-body">
                        <table class="table table-borderless">
                            <tr><th>Username:</th><td>@{{ user.username or 'Chưa cập nhật' }}</td></tr>
                            <tr><th>Số dư hiện tại:</th><td><span class="text-success fw-bold fs-5">{{ "{:,.0f}".format(user.balance) }}đ</span></td></tr>
                            <tr><th>Tổng số lần thuê:</th><td>{{ user.total_rentals }}</td></tr>
                            <tr><th>Tổng chi tiêu:</th><td>{{ "{:,.0f}".format(user.total_spent) }}đ</td></tr>
                            <tr><th>Lợi nhuận mang lại:</th><td><span class="text-success fw-bold">{{ "{:,.0f}".format(user.profit) }}đ</span></td></tr>
                            <tr><th>Trạng thái:</th><td><span class="badge bg-{{ 'success' if not user.is_banned else 'danger' }}">{{ 'Hoạt động' if not user.is_banned else 'Đã bị khóa' }}</span></td></tr>
                            <tr><th>Ngày tham gia:</th><td>{{ user.created_at.strftime('%d/%m/%Y %H:%M') }}</td></tr>
                        </table>
                    </div>
                </div>
            </div>
            <div class="col-md-8">
                <ul class="nav nav-tabs" id="userTab" role="tablist">
                    <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#rentalsTab"><i class="bi bi-telephone"></i> Thuê số <span class="badge bg-primary">{{ rentals|length }}</span></a></li>
                    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#transactionsTab"><i class="bi bi-cash-stack"></i> Giao dịch tiền <span class="badge bg-success">{{ transactions|length }}</span></a></li>
                </ul>
                <div class="tab-content mt-3">
                    <div class="tab-pane fade show active" id="rentalsTab">
                        {% if rentals %}
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead><tr><th>Thời gian</th><th>Dịch vụ</th><th>Số điện thoại</th><th>Giá thuê</th><th>Chi phí</th><th>Lợi nhuận</th><th>Trạng thái</th></tr></thead>
                                <tbody id="rentalsTableBody">
                                    {% for r in rentals %}
                                    <tr>
                                        <td>{{ r.created_at.strftime('%H:%M %d/%m/%Y') }}</td>
                                        <td>{{ r.service_name }}</td>
                                        <td><code>{{ r.phone_number or '—' }}</code></td>
                                        <td class="fw-bold">{{ "{:,.0f}".format(r.price_charged) }}đ</td>
                                        <td class="text-danger">{{ "{:,.0f}".format(r.cost or 0) }}đ</td>
                                        <td class="text-success fw-bold">{{ "{:,.0f}".format(r.price_charged - (r.cost or 0)) }}đ</td>
                                        <td><span class="badge bg-{{ 'success' if r.status == 'success' else 'warning' if r.status == 'waiting' else 'danger' if r.status == 'cancelled' else 'secondary' }}">{{ '✅ Thành công' if r.status == 'success' else '⏳ Chờ OTP' if r.status == 'waiting' else '❌ Đã hủy' if r.status == 'cancelled' else '⏰ Hết hạn' if r.status == 'expired' else r.status }}</span></td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% else %}
                        <div class="text-center py-5"><i class="bi bi-inbox fs-1 text-muted d-block mb-3"></i><h5 class="text-muted">Chưa có lịch sử thuê số</h5></div>
                        {% endif %}
                    </div>
                    <div class="tab-pane fade" id="transactionsTab">
                        {% if transactions %}
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead><tr><th>Thời gian</th><th>Loại</th><th>Số tiền</th><th>Mã giao dịch</th></tr></thead>
                                <tbody>
                                    {% for t in transactions %}
                                    <tr>
                                        <td>{{ t.created_at.strftime('%H:%M %d/%m/%Y') }}</td>
                                        <td><span class="badge bg-success">NẠP TIỀN</span></td>
                                        <td class="text-success fw-bold">+{{ "{:,.0f}".format(t.amount) }}đ</td>
                                        <td><code>{{ t.transaction_code }}</code></td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% else %}
                        <div class="text-center py-5"><i class="bi bi-inbox fs-1 text-muted d-block mb-3"></i><h5 class="text-muted">Chưa có giao dịch tiền</h5></div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
<!-- Các modal giống như ở users template, có thể dùng lại -->
<!-- Modal Cộng tiền, Trừ tiền, Gửi tin nhắn (copy từ USERS_TEMPLATE) -->
'''

# ====================== API ROUTES ======================
@app.route('/api/stats')
def api_stats():
    with app.app_context():
        total_users = User.query.count()
        new_users = User.query.filter(User.created_at >= datetime.now() - timedelta(days=1)).count()
        success_rentals = Rental.query.filter_by(status='success').all()
        rental_revenue = sum(r.price_charged for r in success_rentals)
        rental_cost = sum(r.cost or 0 for r in success_rentals)
        rental_profit = rental_revenue - rental_cost

        qr_deposits = Transaction.query.filter(
            Transaction.type == 'deposit',
            Transaction.status == 'success',
            ~Transaction.transaction_code.like('ADD_%')
        ).all()
        qr_profit = sum(t.amount for t in qr_deposits)

        manual_deposits = Transaction.query.filter(
            Transaction.type == 'deposit',
            Transaction.status == 'success',
            Transaction.transaction_code.like('ADD_%')
        ).all()
        manual_total = sum(t.amount for t in manual_deposits)

        total_profit = qr_profit + rental_profit
        total_revenue = rental_revenue + qr_profit
        profit_margin = (total_profit / total_revenue * 100) if total_revenue else 0

        return jsonify({
            'total_users': total_users,
            'new_users': new_users,
            'total_orders': len(success_rentals),
            'success_orders': len(success_rentals),
            'revenue': total_revenue,
            'cost': rental_cost,
            'qr_deposit': qr_profit,
            'manual_deposit': manual_total,
            'rental': rental_revenue,
            'profit': total_profit,
            'profit_margin': profit_margin
        })

@app.route('/api/recent-transactions')
def api_recent_transactions():
    with app.app_context():
        transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()
        rentals = Rental.query.order_by(Rental.created_at.desc()).limit(10).all()
        all_items = list(transactions) + list(rentals)
        all_items.sort(key=lambda x: x.created_at, reverse=True)
        result = []
        for item in all_items[:10]:
            if hasattr(item, 'type') and item.type == 'deposit':
                user = User.query.get(item.user_id)
                result.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': user.user_id if user else item.user_id,
                    'type': 'Nạp tiền',
                    'service': None,
                    'amount': item.amount,
                    'profit': 0
                })
            elif hasattr(item, 'service_name'):
                user = User.query.get(item.user_id)
                profit = item.price_charged - (item.cost or 0) if item.status == 'success' else 0
                result.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': user.user_id if user else item.user_id,
                    'type': 'Thuê số',
                    'service': item.service_name,
                    'amount': item.price_charged,
                    'profit': profit
                })
        return jsonify(result)

@app.route('/api/users/list')
def api_users_list():
    with app.app_context():
        users = User.query.order_by(User.created_at.desc()).all()
        users_data = []
        for u in users:
            success_rentals = Rental.query.filter_by(user_id=u.id, status='success').all()
            rental_profit = sum(r.price_charged - (r.cost or 0) for r in success_rentals)
            qr_deposits = Transaction.query.filter(
                Transaction.user_id == u.id,
                Transaction.type == 'deposit',
                Transaction.status == 'success',
                ~Transaction.transaction_code.like('ADD_%')
            ).all()
            qr_profit = sum(t.amount for t in qr_deposits)
            total_profit = qr_profit + rental_profit
            users_data.append({
                'id': u.id,
                'user_id': u.user_id,
                'username': u.username or '',
                'balance': u.balance,
                'total_rentals': u.total_rentals,
                'total_spent': sum(r.price_charged for r in success_rentals),
                'profit': total_profit,
                'created_at': u.created_at.strftime('%d/%m/%Y %H:%M'),
                'is_banned': u.is_banned
            })
        return jsonify(users_data)

@app.route('/api/check-otp/<otp_id>/<int:rental_id>', methods=['POST'])
def api_check_otp(otp_id, rental_id):
    from handlers.rent import check_otp_manual
    result = check_otp_manual(otp_id, rental_id)
    return jsonify(result)

@app.route('/api/cancel-rental/<sim_id>/<int:rental_id>', methods=['POST'])
def api_cancel_rental(sim_id, rental_id):
    from handlers.rent import cancel_rental_manual
    result = cancel_rental_manual(sim_id, rental_id)
    return jsonify(result)

@app.route('/api/reuse-number', methods=['POST'])
def api_reuse_number():
    from handlers.rent import reuse_number_manual
    data = request.json
    result = reuse_number_manual(data.get('user_id'), data.get('phone'), data.get('service_id'))
    return jsonify(result)

@app.route('/api/user/<int:user_id>')
def api_user_detail(user_id):
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'Not found'}), 404
        rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).all()
        if not rentals:
            rentals = Rental.query.filter_by(user_id=user_id).order_by(Rental.created_at.desc()).all()
        rentals_data = []
        for r in rentals:
            profit = r.price_charged - (r.cost or 0) if r.status == 'success' else 0
            rentals_data.append({
                'created_at': r.created_at.strftime('%H:%M %d/%m/%Y'),
                'service_name': r.service_name,
                'phone_number': r.phone_number,
                'price_charged': r.price_charged,
                'cost': r.cost or 0,
                'profit': profit,
                'status': r.status,
                'status_display': {'waiting': '⏳ Chờ OTP', 'success': '✅ Thành công', 'cancelled': '❌ Đã hủy', 'expired': '⏰ Hết hạn'}.get(r.status, r.status)
            })
        return jsonify({'rentals': rentals_data})

@app.route('/api/user-recent-rentals/<int:user_id>')
def api_user_recent_rentals(user_id):
    try:
        with app.app_context():
            user = User.query.filter_by(user_id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            recent_rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).limit(100).all()
            result = []
            total_profit = 0
            for r in recent_rentals:
                profit = r.price_charged - (r.cost or 0) if r.status == 'success' else 0
                total_profit += profit
                time_left = ""
                if r.status == 'waiting' and r.expires_at:
                    now = datetime.now()
                    if r.expires_at > now:
                        delta = r.expires_at - now
                        time_left = f"{delta.seconds // 60}:{delta.seconds % 60:02d}"
                    else:
                        time_left = "Hết hạn"
                result.append({
                    'id': r.id,
                    'phone': r.phone_number,
                    'service': r.service_name,
                    'price': r.price_charged,
                    'cost': r.cost or 0,
                    'profit': profit,
                    'status': r.status,
                    'otp': r.otp_code,
                    'otp_id': r.otp_id,
                    'sim_id': r.sim_id,
                    'created_at': r.created_at.strftime('%H:%M %d/%m/%Y'),
                    'expires_at': r.expires_at.strftime('%H:%M %d/%m/%Y') if r.expires_at else None,
                    'time_left': time_left
                })
            return jsonify({
                'user_id': user.user_id,
                'username': user.username,
                'total_rentals': len(recent_rentals),
                'total_profit': total_profit,
                'recent_rentals': result,
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/realtime-transactions')
def api_realtime_transactions():
    try:
        with app.app_context():
            time_threshold = datetime.now() - timedelta(seconds=5)
            new_transactions = Transaction.query.filter(Transaction.created_at >= time_threshold).count()
            new_rentals = Rental.query.filter(Rental.created_at >= time_threshold).count()
            return jsonify({'updates': new_transactions + new_rentals, 'new_transactions': new_transactions, 'new_rentals': new_rentals})
    except Exception as e:
        return jsonify({'error': str(e), 'updates': 0})

@app.route('/api/transactions')
def api_transactions():
    tab = request.args.get('tab', 'all')
    with app.app_context():
        if tab == 'deposit':
            trans = Transaction.query.filter_by(type='deposit').order_by(Transaction.created_at.desc()).limit(200).all()
            rentals = []
        elif tab == 'rental':
            trans = []
            rentals = Rental.query.order_by(Rental.created_at.desc()).limit(200).all()
        elif tab == 'deduct':
            trans = Transaction.query.filter(Transaction.type == 'deduct').order_by(Transaction.created_at.desc()).limit(200).all()
            rentals = []
        else:
            trans = Transaction.query.order_by(Transaction.created_at.desc()).limit(100).all()
            rentals = Rental.query.order_by(Rental.created_at.desc()).limit(100).all()
        transactions_list = []
        for t in trans:
            type_display = 'Nạp tiền' if t.type == 'deposit' else 'Trừ tiền'
            transactions_list.append({
                'time': t.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': t.user_id,
                'type': t.type,
                'type_display': type_display,
                'service': None,
                'amount': t.amount,
                'profit': 0,
                'code': t.transaction_code,
                'status': t.status
            })
        for r in rentals:
            profit = r.price_charged - (r.cost or 0) if r.status == 'success' else 0
            code = getattr(r, 'transaction_code', f"RENTAL_{r.id}_{r.created_at.strftime('%Y%m%d%H%M%S')}")
            transactions_list.append({
                'time': r.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': r.user_id,
                'type': 'rental',
                'type_display': 'Thuê số',
                'service': r.service_name,
                'amount': r.price_charged,
                'profit': profit,
                'code': code,
                'status': r.status
            })
        transactions_list.sort(key=lambda x: x['time'], reverse=True)
        return jsonify(transactions_list)

@app.route('/api/profit-data')
def api_profit_data():
    period = request.args.get('period', 'today')
    now = datetime.now()
    if period == 'today':
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=1)
    elif period == 'week':
        start = now - timedelta(days=now.weekday())
        start = datetime(start.year, start.month, start.day)
        end = start + timedelta(days=7)
    elif period == 'month':
        start = datetime(now.year, now.month, 1)
        end = datetime(now.year, now.month + 1, 1) if now.month < 12 else datetime(now.year + 1, 1, 1)
    else:
        start = datetime(2020, 1, 1)
        end = now + timedelta(days=1)
    with app.app_context():
        qr_deposits = Transaction.query.filter(
            Transaction.type == 'deposit',
            Transaction.status == 'success',
            ~Transaction.transaction_code.like('ADD_%'),
            Transaction.created_at >= start,
            Transaction.created_at < end
        ).all()
        qr_profit = sum(t.amount for t in qr_deposits)
        qr_count = len(qr_deposits)

        rentals = Rental.query.filter(
            Rental.status == 'success',
            Rental.created_at >= start,
            Rental.created_at < end
        ).all()
        rental_revenue = sum(r.price_charged for r in rentals)
        rental_cost = sum(r.cost or 0 for r in rentals)
        rental_profit = rental_revenue - rental_cost
        rental_count = len(rentals)

        service_stats = defaultdict(lambda: {'count': 0, 'revenue': 0, 'cost': 0, 'profit': 0})
        if qr_profit > 0:
            service_stats['💰 NẠP QR'] = {'count': qr_count, 'revenue': qr_profit, 'cost': 0, 'profit': qr_profit}
        for r in rentals:
            service_stats[r.service_name]['count'] += 1
            service_stats[r.service_name]['revenue'] += r.price_charged
            service_stats[r.service_name]['cost'] += r.cost or 0
            service_stats[r.service_name]['profit'] += r.price_charged - (r.cost or 0)

        by_service = []
        for name, data in service_stats.items():
            margin = (data['profit'] / data['revenue'] * 100) if data['revenue'] > 0 else 0
            by_service.append({
                'name': name,
                'count': data['count'],
                'revenue': data['revenue'],
                'cost': data['cost'],
                'profit': data['profit'],
                'margin': margin
            })
        by_service.sort(key=lambda x: x['profit'], reverse=True)

        return jsonify({
            'total_revenue': qr_profit + rental_revenue,
            'total_cost': rental_cost,
            'net_profit': qr_profit + rental_profit,
            'profit_margin': (qr_profit + rental_profit) / (qr_profit + rental_revenue) * 100 if (qr_profit + rental_revenue) > 0 else 0,
            'by_service': by_service,
            'qr_total': qr_profit,
            'manual_total': sum(t.amount for t in Transaction.query.filter(
                Transaction.type == 'deposit',
                Transaction.status == 'success',
                Transaction.transaction_code.like('ADD_%'),
                Transaction.created_at >= start,
                Transaction.created_at < end
            ).all())
        })

@app.route('/api/check-sync')
def api_check_sync():
    """Kiểm tra kết nối đồng bộ"""
    sepay_ok = False
    render_ok = False
    try:
        r = requests.get("https://apisim.codesim.net/health", timeout=3)
        sepay_ok = r.status_code == 200
    except:
        pass
    try:
        r = requests.get(f"{RENDER_URL}/health", timeout=3)
        render_ok = r.status_code == 200
    except:
        pass
    return jsonify({'sepay': sepay_ok, 'render': render_ok})

# ====================== ROUTES TRANG CHÍNH ======================
@app.route('/')
def index():
    now = datetime.now()
    with app.app_context():
        total_users = User.query.count()
        new_users = User.query.filter(User.created_at >= now - timedelta(days=1)).count()
        success_rentals = Rental.query.filter_by(status='success').all()
        rental_revenue = sum(r.price_charged for r in success_rentals)
        rental_cost = sum(r.cost or 0 for r in success_rentals)
        rental_profit = rental_revenue - rental_cost
        qr_deposits = Transaction.query.filter(
            Transaction.type == 'deposit',
            Transaction.status == 'success',
            ~Transaction.transaction_code.like('ADD_%')
        ).all()
        qr_profit = sum(t.amount for t in qr_deposits)
        manual_total = sum(t.amount for t in Transaction.query.filter(
            Transaction.type == 'deposit',
            Transaction.status == 'success',
            Transaction.transaction_code.like('ADD_%')
        ).all())
        total_profit = qr_profit + rental_profit
        total_revenue = rental_revenue + qr_profit
        profit_margin = (total_profit / total_revenue * 100) if total_revenue else 0

        # Lấy 10 giao dịch gần nhất
        recent = []
        all_items = list(Transaction.query.filter_by(status='success').all()) + list(success_rentals)
        all_items.sort(key=lambda x: x.created_at, reverse=True)
        for item in all_items[:10]:
            if hasattr(item, 'type') and item.type == 'deposit':
                user = User.query.get(item.user_id)
                recent.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': user.user_id if user else item.user_id,
                    'type': 'Nạp tiền',
                    'service': None,
                    'amount': item.amount,
                    'profit': item.amount
                })
            elif hasattr(item, 'service_name') and item.status == 'success':
                user = User.query.get(item.user_id)
                profit = item.price_charged - (item.cost or 0)
                recent.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': user.user_id if user else item.user_id,
                    'type': 'Thuê số',
                    'service': item.service_name,
                    'amount': item.price_charged,
                    'profit': profit
                })

        stats = {
            'total_users': total_users,
            'new_users': new_users,
            'total_orders': len(success_rentals),
            'success_orders': len(success_rentals),
            'revenue': total_revenue,
            'cost': rental_cost,
            'qr_deposit': qr_profit,
            'manual_deposit': manual_total,
            'rental': rental_revenue,
            'profit': total_profit,
            'profit_margin': profit_margin,
            'recent_transactions': recent
        }
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', INDEX_TEMPLATE), stats=stats, now=now)

@app.route('/users')
def users():
    with app.app_context():
        users_list = User.query.order_by(User.created_at.desc()).all()
        users_with_profit = []
        for u in users_list:
            success_rentals = Rental.query.filter_by(user_id=u.id, status='success').all()
            rental_profit = sum(r.price_charged - (r.cost or 0) for r in success_rentals)
            qr_deposits = Transaction.query.filter(
                Transaction.user_id == u.id,
                Transaction.type == 'deposit',
                Transaction.status == 'success',
                ~Transaction.transaction_code.like('ADD_%')
            ).all()
            qr_profit = sum(t.amount for t in qr_deposits)
            total_profit = qr_profit + rental_profit
            users_with_profit.append({
                'id': u.id,
                'user_id': u.user_id,
                'username': u.username,
                'balance': u.balance,
                'total_rentals': len(success_rentals),
                'total_spent': sum(r.price_charged for r in success_rentals),
                'created_at': u.created_at.strftime('%d/%m/%Y %H:%M'),
                'is_banned': u.is_banned,
                'profit': total_profit
            })
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', USERS_TEMPLATE), users=users_with_profit, now=datetime.now())

@app.route('/user/<int:user_id>')
def user_detail(user_id):
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first_or_404()
        rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).all()
        if not rentals:
            rentals = Rental.query.filter_by(user_id=user_id).order_by(Rental.created_at.desc()).all()
        transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).all()
        profit = sum(r.price_charged - (r.cost or 0) for r in rentals if r.status == 'success')
        user_data = {
            'user_id': user.user_id,
            'username': user.username,
            'balance': user.balance,
            'total_rentals': len(rentals),
            'total_spent': sum(r.price_charged for r in rentals if r.status == 'success'),
            'is_banned': user.is_banned,
            'profit': profit,
            'created_at': user.created_at
        }
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', USER_DETAIL_TEMPLATE), user=user_data, rentals=rentals, transactions=transactions, now=datetime.now())

@app.route('/profit')
def profit():
    period = request.args.get('period', 'today')
    now = datetime.now()
    if period == 'today':
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=1)
    elif period == 'week':
        start = now - timedelta(days=now.weekday())
        start = datetime(start.year, start.month, start.day)
        end = start + timedelta(days=7)
    elif period == 'month':
        start = datetime(now.year, now.month, 1)
        end = datetime(now.year, now.month + 1, 1) if now.month < 12 else datetime(now.year + 1, 1, 1)
    else:
        start = datetime(2020, 1, 1)
        end = now + timedelta(days=1)
    with app.app_context():
        qr_deposits = Transaction.query.filter(
            Transaction.type == 'deposit',
            Transaction.status == 'success',
            ~Transaction.transaction_code.like('ADD_%'),
            Transaction.created_at >= start,
            Transaction.created_at < end
        ).all()
        qr_profit = sum(t.amount for t in qr_deposits)
        qr_count = len(qr_deposits)

        rentals = Rental.query.filter(
            Rental.status == 'success',
            Rental.created_at >= start,
            Rental.created_at < end
        ).all()
        rental_revenue = sum(r.price_charged for r in rentals)
        rental_cost = sum(r.cost or 0 for r in rentals)
        rental_profit = rental_revenue - rental_cost
        rental_count = len(rentals)

        service_stats = defaultdict(lambda: {'count': 0, 'revenue': 0, 'cost': 0, 'profit': 0})
        if qr_profit > 0:
            service_stats['💰 NẠP QR'] = {'count': qr_count, 'revenue': qr_profit, 'cost': 0, 'profit': qr_profit}
        for r in rentals:
            service_stats[r.service_name]['count'] += 1
            service_stats[r.service_name]['revenue'] += r.price_charged
            service_stats[r.service_name]['cost'] += r.cost or 0
            service_stats[r.service_name]['profit'] += r.price_charged - (r.cost or 0)

        by_service = []
        for name, data in service_stats.items():
            margin = (data['profit'] / data['revenue'] * 100) if data['revenue'] > 0 else 0
            by_service.append({
                'name': name,
                'count': data['count'],
                'revenue': data['revenue'],
                'cost': data['cost'],
                'profit': data['profit'],
                'margin': margin
            })
        by_service.sort(key=lambda x: x['profit'], reverse=True)

        profit_data = {
            'total_revenue': qr_profit + rental_revenue,
            'total_cost': rental_cost,
            'net_profit': qr_profit + rental_profit,
            'profit_margin': (qr_profit + rental_profit) / (qr_profit + rental_revenue) * 100 if (qr_profit + rental_revenue) > 0 else 0,
            'by_service': by_service
        }
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', PROFIT_TEMPLATE), profit=profit_data, period=period, now=now)

@app.route('/transactions')
def transactions():
    tab = request.args.get('tab', 'all')
    with app.app_context():
        if tab == 'deposit':
            trans = Transaction.query.filter_by(type='deposit').order_by(Transaction.created_at.desc()).limit(200).all()
            rentals = []
        elif tab == 'rental':
            trans = []
            rentals = Rental.query.order_by(Rental.created_at.desc()).limit(200).all()
        elif tab == 'deduct':
            trans = Transaction.query.filter_by(type='deduct').order_by(Transaction.created_at.desc()).limit(200).all()
            rentals = []
        else:
            trans = Transaction.query.order_by(Transaction.created_at.desc()).limit(100).all()
            rentals = Rental.query.order_by(Rental.created_at.desc()).limit(100).all()
        transactions_list = []
        for t in trans:
            type_display = 'Nạp tiền' if t.type == 'deposit' else 'Trừ tiền'
            transactions_list.append({
                'time': t.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': t.user_id,
                'type': t.type,
                'type_display': type_display,
                'service': None,
                'amount': t.amount,
                'profit': 0,
                'code': t.transaction_code,
                'status': t.status
            })
        for r in rentals:
            profit = r.price_charged - (r.cost or 0) if r.status == 'success' else 0
            code = getattr(r, 'transaction_code', f"RENTAL_{r.id}_{r.created_at.strftime('%Y%m%d%H%M%S')}")
            transactions_list.append({
                'time': r.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': r.user_id,
                'type': 'rental',
                'type_display': 'Thuê số',
                'service': r.service_name,
                'amount': r.price_charged,
                'profit': profit,
                'code': code,
                'status': r.status
            })
        transactions_list.sort(key=lambda x: x['time'], reverse=True)
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', TRANSACTIONS_TEMPLATE), transactions=transactions_list, tab=tab, now=datetime.now())

@app.route('/statistics')
def statistics():
    stat_type = request.args.get('type', 'daily')
    now = datetime.now()
    stats_data = []
    with app.app_context():
        if stat_type == 'daily':
            for i in range(13, -1, -1):
                date = datetime(now.year, now.month, now.day) - timedelta(days=i)
                next_date = date + timedelta(days=1)
                deposit = sum(t.amount for t in Transaction.query.filter(
                    Transaction.type == 'deposit',
                    Transaction.status == 'success',
                    Transaction.created_at >= date,
                    Transaction.created_at < next_date
                ).all())
                rentals = Rental.query.filter(
                    Rental.status == 'success',
                    Rental.created_at >= date,
                    Rental.created_at < next_date
                ).all()
                rental = sum(r.price_charged for r in rentals)
                cost = sum(r.cost or 0 for r in rentals)
                count = len(rentals) + Transaction.query.filter(
                    Transaction.created_at >= date,
                    Transaction.created_at < next_date
                ).count()
                stats_data.append({
                    'period': date.strftime('%d/%m'),
                    'deposit': deposit,
                    'rental': rental,
                    'cost': cost,
                    'profit': rental - cost,
                    'count': count
                })
        elif stat_type == 'weekly':
            for i in range(5, -1, -1):
                start_week = (now - timedelta(weeks=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                start_week = start_week - timedelta(days=start_week.weekday())
                end_week = start_week + timedelta(days=7)
                deposit = sum(t.amount for t in Transaction.query.filter(
                    Transaction.type == 'deposit',
                    Transaction.status == 'success',
                    Transaction.created_at >= start_week,
                    Transaction.created_at < end_week
                ).all())
                rentals = Rental.query.filter(
                    Rental.status == 'success',
                    Rental.created_at >= start_week,
                    Rental.created_at < end_week
                ).all()
                rental = sum(r.price_charged for r in rentals)
                cost = sum(r.cost or 0 for r in rentals)
                count = len(rentals) + Transaction.query.filter(
                    Transaction.created_at >= start_week,
                    Transaction.created_at < end_week
                ).count()
                stats_data.append({
                    'period': f'Tuần {i+1} ({start_week.strftime("%d/%m")})',
                    'deposit': deposit,
                    'rental': rental,
                    'cost': cost,
                    'profit': rental - cost,
                    'count': count
                })
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', STATISTICS_TEMPLATE), stats_data=stats_data, stat_type=stat_type, now=now)

@app.route('/manual')
def manual():
    with app.app_context():
        manual_trans = Transaction.query.filter(
            Transaction.description.like('%thủ công%') | Transaction.description.like('%trừ tiền%')
        ).order_by(Transaction.created_at.desc()).limit(15).all()
        manual_list = []
        for t in manual_trans:
            user = User.query.get(t.user_id)
            type_text = 'Cộng' if 'Cộng' in t.description or 'cộng' in t.description else 'Trừ'
            manual_list.append({
                'time': t.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': user.user_id if user else 'N/A',
                'type': type_text,
                'amount': t.amount,
                'reason': t.description
            })
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', MANUAL_TEMPLATE), manual_trans=manual_list, now=datetime.now())

@app.route('/broadcast')
def broadcast():
    with app.app_context():
        total_users = User.query.count()
        broadcast_logs = []  # Có thể lấy từ file log nếu cần
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', BROADCAST_TEMPLATE), total_users=total_users, broadcast_logs=broadcast_logs, now=datetime.now())

@app.route('/deduct')
def deduct():
    return redirect(url_for('manual'))

# ====================== XỬ LÝ FORM ======================
@app.route('/add_money', methods=['POST'])
def add_money():
    user_id = request.form.get('user_id', type=int)
    amount = request.form.get('amount', type=int)
    reason = request.form.get('reason', 'Cộng tiền thủ công')
    if not user_id or not amount or amount < 1000:
        return jsonify({'success': False, 'error': 'Thông tin không hợp lệ'})
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'success': False, 'error': f'Không tìm thấy user {user_id}'})
        old_balance = user.balance
        user.balance += amount
        transaction_code = f"ADD_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3).upper()}"
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            type='deposit',
            status='success',
            transaction_code=transaction_code,
            description=f"{reason} (+{format_currency(amount)})",
            created_at=datetime.now()
        )
        db.session.add(transaction)
        db.session.commit()
        logger.info(f"✅ Cộng tiền user {user_id}: {old_balance} → {user.balance}")
        # Push lên Render (nếu cần)
        try:
            push_data = {
                'user_id': user.user_id,
                'balance': user.balance,
                'username': user.username or f"user_{user.user_id}",
                'local_transactions': [{
                    'code': transaction_code,
                    'amount': amount,
                    'user_id': user.user_id,
                    'username': user.username or f"user_{user.user_id}",
                    'status': 'success'
                }]
            }
            requests.post(f"{RENDER_URL}/api/sync-bidirectional", json=push_data, timeout=5)
        except Exception as e:
            logger.error(f"Push thất bại: {e}")
            save_failed_push(user.user_id, user.balance, user.username, transaction_code, amount)
        # Gửi Telegram
        send_telegram_notification(user.user_id,
            f"💰 *NẠP TIỀN THÀNH CÔNG!*\n\n• *Số tiền:* +{amount:,}đ\n• *Mã GD:* `{transaction_code}`\n• *Số dư mới:* {user.balance:,}đ\n• *Lý do:* {reason}")
        return jsonify({'success': True, 'new_balance': user.balance})

@app.route('/deduct_money', methods=['POST'])
def deduct_money():
    user_id = request.form.get('user_id', type=int)
    amount = request.form.get('amount', type=int)
    reason = request.form.get('reason', 'Trừ tiền thủ công')
    if not user_id or not amount or amount < 1000:
        return jsonify({'success': False, 'error': 'Thông tin không hợp lệ'})
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'success': False, 'error': f'Không tìm thấy user {user_id}'})
        if user.balance < amount:
            return jsonify({'success': False, 'error': f'Số dư không đủ! User chỉ có {user.balance:,}đ'})
        old_balance = user.balance
        user.balance -= amount
        transaction_code = f"DEDUCT_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3).upper()}"
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            type='deduct',
            status='success',
            transaction_code=transaction_code,
            description=f"{reason} (-{format_currency(amount)})",
            created_at=datetime.now()
        )
        db.session.add(transaction)
        db.session.commit()
        logger.info(f"✅ Trừ tiền user {user_id}: {old_balance} → {user.balance}")
        # Push lên Render
        try:
            push_data = {
                'user_id': user.user_id,
                'balance': user.balance,
                'username': user.username or f"user_{user.user_id}",
                'local_transactions': [{
                    'code': transaction_code,
                    'amount': amount,
                    'user_id': user.user_id,
                    'username': user.username or f"user_{user.user_id}",
                    'status': 'success'
                }]
            }
            requests.post(f"{RENDER_URL}/api/sync-bidirectional", json=push_data, timeout=5)
        except Exception as e:
            logger.error(f"Push thất bại: {e}")
            save_failed_push(user.user_id, user.balance, user.username, transaction_code, amount)
        send_telegram_notification(user.user_id,
            f"💸 *TRỪ TIỀN THỦ CÔNG*\n\n• *Số tiền:* -{amount:,}đ\n• *Mã GD:* `{transaction_code}`\n• *Số dư mới:* {user.balance:,}đ\n• *Lý do:* {reason}")
        return jsonify({'success': True, 'new_balance': user.balance})

@app.route('/send_message', methods=['POST'])
def send_message():
    user_id = request.form.get('user_id', type=int)
    message = request.form.get('message', '').strip()
    target_type = request.form.get('target_type', 'single')
    if not message:
        return jsonify({'success': False, 'error': 'Thiếu nội dung'})
    if target_type == 'single':
        if not user_id:
            return jsonify({'success': False, 'error': 'Thiếu user_id'})
        success = send_telegram_notification(user_id, message)
        return jsonify({'success': success, 'success_count': 1 if success else 0, 'failed_count': 0 if success else 1})
    elif target_type == 'multiple':
        user_ids_json = request.form.get('user_ids', '[]')
        try:
            user_ids = json.loads(user_ids_json)
        except:
            user_ids = []
        success, failed = send_bulk_telegram(user_ids, message)
        return jsonify({'success': success > 0, 'success_count': success, 'failed_count': failed})
    elif target_type == 'all':
        with app.app_context():
            user_ids = [u.user_id for u in User.query.all()]
        success, failed = send_bulk_telegram(user_ids, message)
        return jsonify({'success': success > 0, 'success_count': success, 'failed_count': failed})
    return jsonify({'success': False, 'error': 'Invalid target_type'})

@app.route('/send_message_bulk', methods=['POST'])
def send_message_bulk():
    user_ids_text = request.form.get('user_ids', '')
    message = request.form.get('message', '').strip()
    if not user_ids_text or not message:
        flash('Thiếu thông tin!', 'danger')
        return redirect(url_for('broadcast'))
    user_ids = [int(line.strip()) for line in user_ids_text.split('\n') if line.strip().isdigit()]
    success, failed = send_bulk_telegram(user_ids, message)
    flash(f'✅ Gửi tin nhắn: {success} thành công, {failed} thất bại', 'success')
    return redirect(url_for('broadcast'))

@app.route('/send_message_all', methods=['POST'])
def send_message_all():
    message = request.form.get('message', '').strip()
    if not message:
        flash('Thiếu nội dung tin nhắn!', 'danger')
        return redirect(url_for('broadcast'))
    with app.app_context():
        user_ids = [u.user_id for u in User.query.all()]
    success, failed = send_bulk_telegram(user_ids, message)
    flash(f'✅ Gửi tin nhắn cho TẤT CẢ user: {success} thành công, {failed} thất bại', 'success')
    return redirect(url_for('broadcast'))

@app.route('/toggle_ban', methods=['POST'])
def toggle_ban():
    data = request.get_json()
    user_id = data.get('user_id')
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if user:
            user.is_banned = not user.is_banned
            db.session.commit()
            status = "bị khóa" if user.is_banned else "được mở khóa"
            send_telegram_notification(user.user_id, f"🔒 *Tài khoản của bạn đã {status}* bởi Admin.")
            return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/export_users')
def export_users():
    with app.app_context():
        users = User.query.all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'User ID', 'Username', 'Số dư', 'Đã thuê', 'Tổng chi', 'Lợi nhuận', 'Ngày tạo', 'Trạng thái'])
        for u in users:
            rentals = Rental.query.filter_by(user_id=u.id, status='success').all()
            profit = sum(r.price_charged - (r.cost or 0) for r in rentals)
            writer.writerow([
                u.id, u.user_id, u.username or '',
                u.balance, u.total_rentals, u.total_spent, profit,
                u.created_at.strftime('%d/%m/%Y %H:%M'),
                'Bị khóa' if u.is_banned else 'Hoạt động'
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=users_export.csv'}
        )

# ====================== KHỞI CHẠY APP ======================
if __name__ == '__main__':
    # Tạo database nếu chưa có
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)