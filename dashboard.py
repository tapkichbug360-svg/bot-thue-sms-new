from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify, Response
from database.models import db, User, Transaction, Rental
from datetime import datetime, timedelta
import os
import secrets
import logging
import json
import requests
from collections import defaultdict
import io
import csv
import asyncio
import time
import threading
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
        
        logger.info(f"💾 Đã lưu push thất bại Dashboard của user {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Lỗi lưu failed push Dashboard: {e}")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Cấu hình database
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'bot.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# API Configuration
API_KEY = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ6emxhbXp6MTEyMiIsImp0aSI6IjgwNTYwIiwiaWF0IjoxNzYxNjEyODAzLCJleHAiOjE4MjM4MjA4MDN9.4u-0IEkd2dgB6QtLEMlgp0KG55JwDDfMiNd98BQNzuJljOA9UTDymPsqnheIqGFM7WVGx94iV71tZasx62JIvw"
BASE_URL = "https://apisim.codesim.net"

# Token Telegram
BOT_TOKEN = os.getenv('BOT_TOKEN', '8561464326:AAG6NPFNvvFV0vFWQP1t8qUMo3WrjW5Un90')

# ====================== HÀM GỬI TELEGRAM ======================
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

def format_currency(amount):
    """Định dạng tiền tệ"""
    return f"{amount:,}đ"

# ====================== BASE TEMPLATE ======================
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Thuê SMS - Dashboard Quản Trị Chuyên Nghiệp</title>
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
    </style>
</head>
<body>
    <!-- SCRIPT ĐỒNG HỒ - ĐẶT NGAY ĐẦU BODY -->
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
        $(document).ready(function() {
            $('.datatable').DataTable({
                language: { url: '//cdn.datatables.net/plug-ins/1.13.7/i18n/vi.json' },
                pageLength: 15,
                responsive: true,
                order: [[0, 'desc']]
            });
        });
        
        function updatePreview() {
            let message = document.getElementById('message').value;
            let preview = document.getElementById('messagePreview');
            if (message) {
                preview.innerHTML = message.replace(/\n/g, '<br>');
            } else {
                preview.innerHTML = '<span class="text-muted">Nhập nội dung tin nhắn...</span>';
            }
        }

        // ===== TỰ ĐỘNG CẬP NHẬT DỮ LIỆU MỖI 1 GIÂY =====
        function updateData() {
            const path = window.location.pathname;
            
            if (path === '/') {
                updateDashboard();
                updateRecentTransactions();
            } else if (path === '/users') {
                updateUsersTable();
            } else if (path.startsWith('/user/')) {
                updateUserDetail();
            }
        }
        
        // Cập nhật trang chủ
        function updateDashboard() {
            fetch('/api/stats')
                .then(response => response.json())
                .then(stats => {
                    // Cập nhật số liệu thống kê
                    const statNumbers = document.querySelectorAll('.stat-number');
                    if (statNumbers.length >= 4) {
                        statNumbers[0].textContent = stats.total_users.toLocaleString();
                        statNumbers[1].textContent = stats.new_users.toLocaleString();
                        statNumbers[2].textContent = stats.total_orders.toLocaleString();
                        statNumbers[3].textContent = stats.success_orders.toLocaleString();
                    }
                    
                    // Cập nhật doanh thu
                    const revenueEl = document.querySelector('.stat-number.text-success');
                    if (revenueEl) revenueEl.textContent = stats.revenue.toLocaleString() + 'đ';
                    
                    // Cập nhật chi phí
                    const costEl = document.querySelector('.stat-number.text-danger');
                    if (costEl) costEl.textContent = stats.cost.toLocaleString() + 'đ';
                    
                    // Cập nhật lợi nhuận
                    const profitEl = document.querySelector('.profit-number');
                    if (profitEl) profitEl.textContent = stats.profit.toLocaleString() + 'đ';
                });
        }
        
        // Cập nhật bảng giao dịch gần đây
        function updateRecentTransactions() {
            fetch('/api/recent-transactions')
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
        
        // Cập nhật bảng users
        function updateUsersTable() {
            fetch('/api/users/list')
                .then(response => response.json())
                .then(users => {
                    const tbody = document.querySelector('#usersTable tbody');
                    if (!tbody) return;
                    
                    let html = '';
                    users.forEach(user => {
                        html += `<tr data-user-id="${user.user_id}">
                            <td><input type="checkbox" class="user-checkbox" value="${user.user_id}"></td>
                            <td>${user.id}</td>
                            <td><code>${user.user_id}</code></td>
                            <td>@${user.username || 'N/A'}</td>
                            <td class="fw-bold text-success balance-cell">${user.balance.toLocaleString()}đ</td>
                            <td class="rentals-cell">${user.total_rentals}</td>
                            <td>${user.total_spent.toLocaleString()}đ</td>
                            <td class="text-success fw-bold profit-cell">${user.profit.toLocaleString()}đ</td>
                            <td>${user.created_at}</td>
                            <td><span class="badge bg-${user.is_banned ? 'danger' : 'success'}">${user.is_banned ? 'Bị khóa' : 'Hoạt động'}</span></td>
                            <td>
                                <button class="btn btn-sm btn-primary" onclick="addMoney(${user.user_id})"><i class="bi bi-plus-circle"></i></button>
                                <button class="btn btn-sm btn-warning" onclick="deductMoney(${user.user_id})"><i class="bi bi-dash-circle"></i></button>
                                <button class="btn btn-sm btn-info text-white" onclick="sendMessage(${user.user_id})"><i class="bi bi-chat"></i></button>
                                <button class="btn btn-sm btn-${user.is_banned ? 'success' : 'danger'}" onclick="toggleBan(${user.user_id})"><i class="bi bi-${user.is_banned ? 'unlock' : 'lock'}"></i></button>
                                <a href="/user/${user.user_id}" class="btn btn-sm btn-info text-white"><i class="bi bi-eye-fill"></i></a>
                            </td>
                        </tr>`;
                    });
                    tbody.innerHTML = html;
                });
        }
        
        // Cập nhật chi tiết user
        function updateUserDetail() {
            const userId = window.location.pathname.split('/').pop();
            fetch(`/api/user/${userId}`)
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
                                <td><span class="badge bg-${r.status === 'success' ? 'success' : r.status === 'waiting' ? 'warning' : 'danger'}">${r.status}</span></td>
                            </tr>`;
                        });
                        rentalsTbody.innerHTML = html;
                    }
                });
        }
        
        // Chạy update mỗi 1 giây
        setInterval(updateData, 1000);
        
        // ===== CẬP NHẬT REALTIME CHO DASHBOARD =====
        function updateRealtimeData() {
            const path = window.location.pathname;
            
            // Cập nhật trang users
            if (path === '/users') {
                fetch('/api/users/list?_=' + new Date().getTime())
                    .then(response => response.json())
                    .then(users => {
                        users.forEach(user => {
                            // Tìm dòng tương ứng trong bảng
                            let row = document.querySelector(`tr[data-user-id="${user.user_id}"]`);
                            if (row) {
                                let updated = false;
                                
                                // Cập nhật số dư (cột thứ 5)
                                let balanceCell = row.querySelector('.balance-cell');
                                if (balanceCell) {
                                    let oldBalance = balanceCell.textContent;
                                    let newBalance = user.balance.toLocaleString() + 'đ';
                                    if (oldBalance !== newBalance) {
                                        balanceCell.textContent = newBalance;
                                        updated = true;
                                    }
                                }
                                
                                // Cập nhật số lần thuê (cột thứ 6)
                                let rentalsCell = row.querySelector('.rentals-cell');
                                if (rentalsCell) {
                                    let oldRentals = rentalsCell.textContent;
                                    let newRentals = user.total_rentals;
                                    if (oldRentals != newRentals) {
                                        rentalsCell.textContent = newRentals;
                                        updated = true;
                                    }
                                }
                                
                                // Cập nhật lợi nhuận (cột thứ 8)
                                let profitCell = row.querySelector('.profit-cell');
                                if (profitCell) {
                                    let oldProfit = profitCell.textContent;
                                    let newProfit = user.profit.toLocaleString() + 'đ';
                                    if (oldProfit !== newProfit) {
                                        profitCell.textContent = newProfit;
                                        updated = true;
                                    }
                                }
                                
                                // Highlight nếu có thay đổi
                                if (updated) {
                                    row.classList.add('highlight-update');
                                    setTimeout(() => {
                                        row.classList.remove('highlight-update');
                                    }, 1000);
                                }
                            }
                        });
                    })
                    .catch(error => console.log('Realtime update error:', error));
            }
            
            // Cập nhật dashboard
            else if (path === '/') {
                fetch('/api/stats?_=' + new Date().getTime())
                    .then(response => response.json())
                    .then(stats => {
                        // Cập nhật số liệu thống kê
                        const statNumbers = document.querySelectorAll('.stat-number');
                        if (statNumbers.length >= 4) {
                            statNumbers[0].textContent = stats.total_users.toLocaleString();
                            statNumbers[1].textContent = stats.new_users.toLocaleString();
                            statNumbers[2].textContent = stats.total_orders.toLocaleString();
                            statNumbers[3].textContent = stats.success_orders.toLocaleString();
                        }
                        
                        // Cập nhật doanh thu
                        let revenueEl = document.querySelector('.stat-number.text-success');
                        if (revenueEl) revenueEl.textContent = stats.revenue.toLocaleString() + 'đ';
                        
                        // Cập nhật chi phí
                        let costEl = document.querySelector('.stat-number.text-danger');
                        if (costEl) costEl.textContent = stats.cost.toLocaleString() + 'đ';
                        
                        // Cập nhật lợi nhuận
                        let profitEl = document.querySelector('.profit-number');
                        if (profitEl) profitEl.textContent = stats.profit.toLocaleString() + 'đ';
                    });
            }
            
            // Cập nhật chi tiết user
            else if (path.startsWith('/user/')) {
                const userId = path.split('/').pop();
                fetch(`/api/user/${userId}?_=` + new Date().getTime())
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) return;
                        
                        // Cập nhật số dư trong phần thông tin user
                        let balanceElement = document.querySelector('.text-success.fw-bold.fs-5');
                        if (balanceElement) {
                            // Lấy balance từ API users/list hoặc từ data hiện tại
                            fetch('/api/users/list?_=' + new Date().getTime())
                                .then(response => response.json())
                                .then(users => {
                                    let user = users.find(u => u.user_id == userId);
                                    if (user) {
                                        balanceElement.textContent = user.balance.toLocaleString() + 'đ';
                                    }
                                });
                        }
                    });
            }
        }

        // Chạy cập nhật realtime mỗi 3 giây
        setInterval(updateRealtimeData, 3000);
        
        // Chạy ngay khi load trang
        document.addEventListener('DOMContentLoaded', function() {
            updateRealtimeData();
        });
        
        // Các hàm xử lý modal
        let selectedUsers = [];

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

        function updateSelectedCount() {
            document.getElementById('selectedCount').innerText = `Đã chọn ${selectedUsers.length} user`;
        }

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

        document.getElementById('addMoneyForm').addEventListener('submit', function(e) {
            e.preventDefault();
            fetch('/add_money', {
                method: 'POST',
                body: new URLSearchParams(new FormData(this))
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Lỗi: ' + data.error);
                }
            })
            .catch(error => {
                alert('Lỗi kết nối: ' + error);
            });
        });

        document.getElementById('deductMoneyForm').addEventListener('submit', function(e) {
            e.preventDefault();
            fetch('/deduct_money', {
                method: 'POST',
                body: new URLSearchParams(new FormData(this))
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Lỗi: ' + data.error);
                }
            })
            .catch(error => {
                alert('Lỗi kết nối: ' + error);
            });
        });

        document.getElementById('sendMessageForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            let formData = new FormData(this);
            let targetType = document.getElementById('msg_target_type').value;
            
            if (targetType === 'multiple') {
                formData.append('user_ids', JSON.stringify(selectedUsers));
            }
            
            fetch('/send_message', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(`✅ Gửi thành công!\n• Thành công: ${data.success_count}\n• Thất bại: ${data.failed_count}`);
                    bootstrap.Modal.getInstance(document.getElementById('sendMessageModal')).hide();
                } else {
                    alert('Lỗi: ' + data.error);
                }
            })
            .catch(error => {
                alert('Lỗi kết nối: ' + error);
            });
        });

        function toggleBan(userId) {
            if(confirm('Bạn chắc chắn muốn thay đổi trạng thái khóa user này?')) {
                fetch('/toggle_ban', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: userId})})
                .then(() => location.reload());
            }
        }

        function exportToExcel() { window.location.href = '/export_users'; }

        document.getElementById('searchInput').addEventListener('keyup', function() {
            let val = this.value.toLowerCase();
            document.querySelectorAll('#usersTable tbody tr').forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(val) ? '' : 'none';
            });
        });
    </script>
</body>
</html>
'''

# ====================== INDEX TEMPLATE ======================
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
                                <p class="text-muted">Tổng doanh thu</p>
                                <div class="row text-start mt-3">
                                    <div class="col-6"><strong>Nạp tiền</strong><br><span class="text-success">{{ "{:,.0f}".format(stats.deposit) }}đ</span></div>
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
                                <p class="text-muted">Sau khi trừ toàn bộ chi phí</p>
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

# ====================== USERS TEMPLATE ======================
USERS_TEMPLATE = '''
<div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
        <h5><i class="bi bi-people-fill"></i> Quản lý người dùng & Chi tiết giao dịch</h5>
        <div>
            <button class="btn btn-info text-white me-2" onclick="broadcastToAll()"><i class="bi bi-megaphone-fill"></i> Gửi tin cho tất cả</button>
            <button class="btn btn-success" onclick="exportToExcel()"><i class="bi bi-file-earmark-excel"></i> Xuất Excel</button>
        </div>
    </div>
    <div class="card-body">
        <input type="text" id="searchInput" class="search-box mb-4 w-100" placeholder="🔍 Tìm kiếm User ID, Username, Số dư...">
        
        <!-- Bảng danh sách users -->
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
                    <td>{{ user.created_at.strftime('%d/%m/%Y %H:%M') }}</td>
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
                    <button type="submit" class="btn btn-info text-white">
                        <i class="bi bi-send"></i> Gửi tin nhắn
                    </button>
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
                    <div class="col-md-6">
                        <strong>User ID:</strong> <code id="modalUserId"></code>
                    </div>
                    <div class="col-md-6">
                        <strong>Tổng số thuê:</strong> <span id="modalTotalRentals" class="badge bg-primary"></span>
                    </div>
                </div>
                
                <div class="table-responsive">
                    <table class="table table-striped table-hover" id="modalRentalsTable">
                        <thead>
                            <tr>
                                <th>Thời gian</th>
                                <th>Số điện thoại</th>
                                <th>Dịch vụ</th>
                                <th>Giá thuê</th>
                                <th>OTP</th>
                                <th>Trạng thái</th>
                                <th>Hết hạn</th>
                                <th>Thao tác</th>
                            </tr>
                        </thead>
                        <tbody id="modalRentalsBody">
                            <tr>
                                <td colspan="8" class="text-center">
                                    <div class="spinner-border text-primary" role="status">
                                        <span class="visually-hidden">Đang tải...</span>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
                <button type="button" class="btn btn-primary" onclick="refreshUserRentals()">
                    <i class="bi bi-arrow-repeat"></i> Làm mới
                </button>
            </div>
        </div>
    </div>
</div>

<script>
let selectedUsers = [];
let currentUserId = null;

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

function updateSelectedCount() {
    document.getElementById('selectedCount').innerText = `Đã chọn ${selectedUsers.length} user`;
}

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

// Xem chi tiết số thuê của user
function viewUserRentals(userId, username) {
    currentUserId = userId;
    document.getElementById('modalUserName').innerText = username || 'User ' + userId;
    document.getElementById('modalUserId').innerText = userId;
    
    const modal = new bootstrap.Modal(document.getElementById('userRentalsModal'));
    modal.show();
    
    loadUserRentals(userId);
}

// Tải 100 số thuê gần nhất của user
function loadUserRentals(userId) {
    const tbody = document.getElementById('modalRentalsBody');
    tbody.innerHTML = '<tr><td colspan="8" class="text-center"><div class="spinner-border text-primary"></div></td></tr>';
    
    fetch(`/api/user-recent-rentals/${userId}?_=` + new Date().getTime())
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
                let actions = '';
                
                if (r.status === 'success') {
                    statusClass = 'success';
                    statusText = '✅ Thành công';
                } else if (r.status === 'cancelled') {
                    statusClass = 'danger';
                    statusText = '❌ Đã hủy';
                } else if (r.status === 'expired') {
                    statusClass = 'secondary';
                    statusText = '⏰ Hết hạn';
                } else if (r.status === 'waiting') {
                    actions = `
                        <button class="btn btn-sm btn-primary" onclick="checkOTP('${r.otp_id}', ${r.id})">
                            <i class="bi bi-search"></i>
                        </button>
                    `;
                }
                
                let otpDisplay = r.otp ? `<code>${r.otp}</code>` : '—';
                if (r.otp && r.otp.includes('Audio')) {
                    otpDisplay = '<span class="badge bg-info">🔊 Audio</span>';
                }
                
                html += `<tr>
                    <td><small>${r.created_at}</small></td>
                    <td><code>${r.phone}</code></td>
                    <td>${r.service}</td>
                    <td class="fw-bold text-danger">${r.price.toLocaleString()}đ</td>
                    <td>${otpDisplay}</td>
                    <td><span class="badge bg-${statusClass}">${statusText}</span></td>
                    <td><small>${r.expires_at || '—'}</small></td>
                    <td>${actions}</td>
                </tr>`;
            });
            
            tbody.innerHTML = html;
        })
        .catch(error => {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Lỗi tải dữ liệu</td></tr>';
            console.log('Lỗi:', error);
        });
}

// Làm mới danh sách
function refreshUserRentals() {
    if (currentUserId) {
        loadUserRentals(currentUserId);
    }
}

// Cập nhật realtime mỗi 5 giây (chỉ khi modal đang mở)
setInterval(() => {
    if (document.getElementById('userRentalsModal').classList.contains('show') && currentUserId) {
        loadUserRentals(currentUserId);
    }
}, 5000);

// Các hàm xử lý form
document.getElementById('addMoneyForm').addEventListener('submit', function(e) {
    e.preventDefault();
    fetch('/add_money', {
        method: 'POST',
        body: new URLSearchParams(new FormData(this))
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Lỗi: ' + data.error);
        }
    })
    .catch(error => {
        alert('Lỗi kết nối: ' + error);
    });
});

document.getElementById('deductMoneyForm').addEventListener('submit', function(e) {
    e.preventDefault();
    fetch('/deduct_money', {
        method: 'POST',
        body: new URLSearchParams(new FormData(this))
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Lỗi: ' + data.error);
        }
    })
    .catch(error => {
        alert('Lỗi kết nối: ' + error);
    });
});

document.getElementById('sendMessageForm').addEventListener('submit', function(e) {
    e.preventDefault();
    
    let formData = new FormData(this);
    let targetType = document.getElementById('msg_target_type').value;
    
    if (targetType === 'multiple') {
        formData.append('user_ids', JSON.stringify(selectedUsers));
    }
    
    fetch('/send_message', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(`✅ Gửi thành công!\n• Thành công: ${data.success_count}\n• Thất bại: ${data.failed_count}`);
            bootstrap.Modal.getInstance(document.getElementById('sendMessageModal')).hide();
        } else {
            alert('Lỗi: ' + data.error);
        }
    })
    .catch(error => {
        alert('Lỗi kết nối: ' + error);
    });
});

function toggleBan(userId) {
    if(confirm('Bạn chắc chắn muốn thay đổi trạng thái khóa user này?')) {
        fetch('/toggle_ban', {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({user_id: userId})
        })
        .then(() => location.reload());
    }
}

function exportToExcel() { 
    window.location.href = '/export_users'; 
}

document.getElementById('searchInput').addEventListener('keyup', function() {
    let val = this.value.toLowerCase();
    document.querySelectorAll('#usersTable tbody tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(val) ? '' : 'none';
    });
});
</script>
'''

# ====================== PROFIT TEMPLATE ======================
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

# ====================== TRANSACTIONS TEMPLATE ======================
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

# ====================== MANUAL TEMPLATE ======================
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

# ====================== BROADCAST TEMPLATE ======================
BROADCAST_TEMPLATE = '''
<div class="row">
    <div class="col-lg-8 mx-auto">
        <div class="card">
            <div class="card-header bg-info text-white">
                <h5><i class="bi bi-megaphone-fill"></i> Gửi thông báo hàng loạt</h5>
            </div>
            <div class="card-body">
                <ul class="nav nav-tabs mb-4">
                    <li class="nav-item">
                        <a class="nav-link active" data-bs-toggle="tab" href="#single">Gửi cho 1 user</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" data-bs-toggle="tab" href="#multiple">Gửi cho nhiều user</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" data-bs-toggle="tab" href="#all">Gửi cho tất cả</a>
                    </li>
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
                            <button type="submit" class="btn btn-info text-white w-100 py-2">
                                <i class="bi bi-send"></i> Gửi tin nhắn
                            </button>
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
                            <button type="submit" class="btn btn-info text-white w-100 py-2">
                                <i class="bi bi-send"></i> Gửi tin nhắn
                            </button>
                        </form>
                    </div>
                    
                    <div class="tab-pane fade" id="all">
                        <form method="POST" action="/send_message_all" onsubmit="return confirm('⚠️ Bạn có chắc muốn gửi tin nhắn cho TẤT CẢ user?\nSố lượng: {{ total_users }} user')">
                            <div class="mb-3">
                                <label class="form-label fw-bold">Nội dung tin nhắn</label>
                                <textarea class="form-control" name="message" rows="5" required placeholder="Nhập nội dung..."></textarea>
                                <div class="form-text">Tin nhắn sẽ được gửi đến {{ total_users }} user</div>
                            </div>
                            <button type="submit" class="btn btn-info text-white w-100 py-2">
                                <i class="bi bi-send"></i> Gửi cho tất cả ({{ total_users }} user)
                            </button>
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

# ====================== STATISTICS TEMPLATE ======================
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

# ====================== USER DETAIL TEMPLATE ======================
USER_DETAIL_TEMPLATE = '''
<div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
        <h5><i class="bi bi-person-fill"></i> CHI TIẾT USER #{{ user.user_id }}</h5>
        <div>
            <button class="btn btn-info text-white btn-sm me-2" onclick="sendMessage({{ user.user_id }})">
                <i class="bi bi-chat"></i> Nhắn tin
            </button>
            <button class="btn btn-success btn-sm me-2" onclick="addMoney({{ user.user_id }})">
                <i class="bi bi-plus-circle"></i> Cộng tiền
            </button>
            <button class="btn btn-warning btn-sm me-2" onclick="deductMoney({{ user.user_id }})">
                <i class="bi bi-dash-circle"></i> Trừ tiền
            </button>
            <a href="/users" class="btn btn-secondary btn-sm">
                <i class="bi bi-arrow-left"></i> Quay lại
            </a>
        </div>
    </div>
    
    <div class="card-body">
        <div class="row">
            <div class="col-md-4">
                <div class="card h-100">
                    <div class="card-header bg-primary text-white">
                        <h6 class="mb-0"><i class="bi bi-info-circle"></i> Thông tin cơ bản</h6>
                    </div>
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
                    <li class="nav-item">
                        <a class="nav-link active" data-bs-toggle="tab" href="#rentalsTab">
                            <i class="bi bi-telephone"></i> Thuê số <span class="badge bg-primary">{{ rentals|length }}</span>
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" data-bs-toggle="tab" href="#transactionsTab">
                            <i class="bi bi-cash-stack"></i> Giao dịch tiền <span class="badge bg-success">{{ transactions|length }}</span>
                        </a>
                    </li>
                </ul>
                
                <div class="tab-content mt-3">
                    <div class="tab-pane fade show active" id="rentalsTab">
                        {% if rentals %}
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead>
                                    <tr>
                                        <th>Thời gian</th>
                                        <th>Dịch vụ</th>
                                        <th>Số điện thoại</th>
                                        <th>Giá thuê</th>
                                        <th>Chi phí</th>
                                        <th>Lợi nhuận</th>
                                        <th>Trạng thái</th>
                                    </tr>
                                </thead>
                                <tbody id="rentalsTableBody">
                                    {% for r in rentals %}
                                    <tr>
                                        <td>{{ r.created_at.strftime('%H:%M %d/%m/%Y') }}</td>
                                        <td>{{ r.service_name }}</td>
                                        <td><code>{{ r.phone_number or '—' }}</code></td>
                                        <td class="fw-bold">{{ "{:,.0f}".format(r.price_charged) }}đ</td>
                                        <td class="text-danger">{{ "{:,.0f}".format(r.cost or 0) }}đ</td>
                                        <td class="text-success fw-bold">{{ "{:,.0f}".format(r.price_charged - (r.cost or 0)) }}đ</td>
                                        <td><span class="badge bg-{{ 'success' if r.status == 'success' else 'warning' if r.status == 'waiting' else 'danger' }}">{{ r.status }}</span></td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% else %}
                        <div class="text-center py-5">
                            <i class="bi bi-inbox fs-1 text-muted d-block mb-3"></i>
                            <h5 class="text-muted">Chưa có lịch sử thuê số</h5>
                            <p class="text-muted">User này chưa thực hiện giao dịch thuê số nào.</p>
                        </div>
                        {% endif %}
                    </div>
                    
                    <div class="tab-pane fade" id="transactionsTab">
                        {% if transactions %}
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead>
                                    <tr>
                                        <th>Thời gian</th>
                                        <th>Loại</th>
                                        <th>Số tiền</th>
                                        <th>Mã giao dịch</th>
                                    </tr>
                                </thead>
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
                        <div class="text-center py-5">
                            <i class="bi bi-inbox fs-1 text-muted d-block mb-3"></i>
                            <h5 class="text-muted">Chưa có giao dịch tiền</h5>
                        </div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Modal Cộng tiền -->
<div class="modal fade" id="addMoneyModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header bg-success text-white">
                <h5 class="modal-title"><i class="bi bi-plus-circle-fill"></i> Cộng tiền cho user {{ user.user_id }}</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <form id="addMoneyForm" method="POST" action="/add_money">
                <div class="modal-body">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
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
            <div class="modal-header bg-warning">
                <h5 class="modal-title"><i class="bi bi-dash-circle-fill"></i> Trừ tiền user {{ user.user_id }}</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <form id="deductMoneyForm" method="POST" action="/deduct_money">
                <div class="modal-body">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
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
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header bg-info text-white">
                <h5 class="modal-title"><i class="bi bi-chat-dots-fill"></i> Gửi tin nhắn cho user {{ user.user_id }}</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <form id="sendMessageForm">
                <div class="modal-body">
                    <input type="hidden" name="user_id" value="{{ user.user_id }}">
                    <div class="mb-3">
                        <label class="form-label fw-bold">Nội dung tin nhắn</label>
                        <textarea class="form-control" name="message" rows="5" required placeholder="Nhập nội dung..."></textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="submit" class="btn btn-info text-white">Gửi tin nhắn</button>
                </div>
            </form>
        </div>
    </div>
</div>

<script>
function addMoney(userId) { new bootstrap.Modal(document.getElementById('addMoneyModal')).show(); }
function deductMoney(userId) { new bootstrap.Modal(document.getElementById('deductMoneyModal')).show(); }
function sendMessage(userId) { new bootstrap.Modal(document.getElementById('sendMessageModal')).show(); }

document.getElementById('addMoneyForm')?.addEventListener('submit', function(e) {
    e.preventDefault();
    fetch('/add_money', {
        method: 'POST',
        body: new URLSearchParams(new FormData(this))
    }).then(response => response.json()).then(data => {
        if (data.success) location.reload();
        else alert('Lỗi: ' + data.error);
    });
});

document.getElementById('deductMoneyForm')?.addEventListener('submit', function(e) {
    e.preventDefault();
    fetch('/deduct_money', {
        method: 'POST',
        body: new URLSearchParams(new FormData(this))
    }).then(response => response.json()).then(data => {
        if (data.success) location.reload();
        else alert('Lỗi: ' + data.error);
    });
});

document.getElementById('sendMessageForm')?.addEventListener('submit', function(e) {
    e.preventDefault();
    fetch('/send_message', {
        method: 'POST',
        body: new URLSearchParams(new FormData(this))
    }).then(response => response.json()).then(data => {
        if (data.success) {
            alert('✅ Đã gửi tin nhắn thành công!');
            bootstrap.Modal.getInstance(document.getElementById('sendMessageModal')).hide();
        } else alert('Lỗi: ' + data.error);
    });
});
</script>
'''

# ====================== API ROUTES ======================
@app.route('/api/stats')
def api_stats():
    """API trả về thống kê cho trang chủ"""
    with app.app_context():
        total_users = User.query.count()
        new_users = User.query.filter(User.created_at >= datetime.now() - timedelta(days=1)).count()
        rentals = Rental.query.all()
        
        rental_total = sum(r.price_charged for r in rentals if r.status == 'success')
        api_cost = sum(r.cost or 0 for r in rentals if r.status == 'success')
        profit_val = rental_total - api_cost
        
        return jsonify({
            'total_users': total_users,
            'new_users': new_users,
            'total_orders': len(rentals),
            'success_orders': len([r for r in rentals if r.status == 'success']),
            'revenue': rental_total,
            'cost': api_cost,
            'profit': profit_val
        })

@app.route('/api/recent-transactions')
def api_recent_transactions():
    """API trả về 10 giao dịch gần nhất"""
    with app.app_context():
        transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()
        rentals = Rental.query.order_by(Rental.created_at.desc()).limit(10).all()
        
        recent = []
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
                result.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': user.user_id if user else item.user_id,
                    'type': 'Thuê số',
                    'service': item.service_name,
                    'amount': item.price_charged,
                    'profit': item.price_charged - (item.cost or 0)
                })
        
        return jsonify(result)

@app.route('/api/users/list')
def api_users_list():
    """API trả về danh sách users"""
    with app.app_context():
        users = User.query.order_by(User.created_at.desc()).all()
        users_data = []
        for u in users:
            rentals = Rental.query.filter_by(user_id=u.id, status='success').all()
            profit = sum(r.price_charged - (r.cost or 0) for r in rentals)
            users_data.append({
                'id': u.id,
                'user_id': u.user_id,
                'username': u.username or '',
                'balance': u.balance,
                'total_rentals': u.total_rentals,
                'total_spent': u.total_spent,
                'profit': profit,
                'created_at': u.created_at.strftime('%d/%m/%Y %H:%M'),
                'is_banned': u.is_banned
            })
        return jsonify(users_data)
@app.route('/api/check-otp/<otp_id>/<int:rental_id>', methods=['POST'])
def api_check_otp(otp_id, rental_id):
    """API kiểm tra OTP từ dashboard"""
    # Gọi hàm check OTP từ rent.py
    from handlers.rent import check_otp_manual
    result = check_otp_manual(otp_id, rental_id)
    return jsonify(result)

@app.route('/api/cancel-rental/<sim_id>/<int:rental_id>', methods=['POST'])
def api_cancel_rental(sim_id, rental_id):
    """API hủy số từ dashboard"""
    # Gọi hàm cancel từ rent.py
    from handlers.rent import cancel_rental_manual
    result = cancel_rental_manual(sim_id, rental_id)
    return jsonify(result)

@app.route('/api/reuse-number', methods=['POST'])
def api_reuse_number():
    """API thuê lại số từ dashboard"""
    data = request.json
    user_id = data.get('user_id')
    phone = data.get('phone')
    service_id = data.get('service_id')
    
    # Gọi hàm reuse từ rent.py
    from handlers.rent import reuse_number_manual
    result = reuse_number_manual(user_id, phone, service_id)
    return jsonify(result)

@app.route('/api/user/<int:user_id>')
def api_user_detail(user_id):
    """API trả về chi tiết user"""
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'Not found'}), 404
        
        rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).all()
        if not rentals:
            rentals = Rental.query.filter_by(user_id=user_id).order_by(Rental.created_at.desc()).all()
        
        rentals_data = []
        for r in rentals:
            rentals_data.append({
                'created_at': r.created_at.strftime('%H:%M %d/%m/%Y'),
                'service_name': r.service_name,
                'phone_number': r.phone_number,
                'price_charged': r.price_charged,
                'cost': r.cost or 0,
                'profit': r.price_charged - (r.cost or 0),
                'status': r.status
            })
        
        return jsonify({'rentals': rentals_data})

# ====================== ROUTES ======================
@app.route('/')
def index():
    now = datetime.now()
    with app.app_context():
        total_users = User.query.count()
        new_users = User.query.filter(User.created_at >= now - timedelta(days=1)).count()
        transactions = Transaction.query.all()
        rentals = Rental.query.all()
        
        deposit_total = sum(t.amount for t in transactions if t.type == 'deposit' and t.status == 'success')
        rental_total = sum(r.price_charged for r in rentals if r.status == 'success')
        api_cost = sum(r.cost or 0 for r in rentals if r.status == 'success')
        profit_val = rental_total - api_cost
        
        recent = []
        all_items = list(transactions) + list(rentals)
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
                    'profit': 0
                })
            elif hasattr(item, 'service_name'):
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
            'total_orders': len(rentals),
            'success_orders': len([r for r in rentals if r.status == 'success']),
            'revenue': deposit_total + rental_total,
            'deposit': deposit_total,
            'rental': rental_total,
            'cost': api_cost,
            'profit': profit_val,
            'profit_margin': (profit_val / rental_total * 100) if rental_total > 0 else 0,
            'recent_transactions': recent
        }
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', INDEX_TEMPLATE),
        stats=stats, now=now
    )

@app.route('/users')
def users():
    with app.app_context():
        users_list = User.query.order_by(User.created_at.desc()).all()
        users_with_profit = []
        for u in users_list:
            user_rentals = Rental.query.filter_by(user_id=u.id, status='success').all()
            profit = sum(r.price_charged - (r.cost or 0) for r in user_rentals)
            users_with_profit.append({
                'id': u.id,
                'user_id': u.user_id,
                'username': u.username,
                'balance': u.balance,
                'total_rentals': u.total_rentals,
                'total_spent': u.total_spent,
                'created_at': u.created_at,
                'is_banned': u.is_banned,
                'profit': profit
            })
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', USERS_TEMPLATE),
        users=users_with_profit, now=datetime.now()
    )
@app.route('/api/user-recent-rentals/<int:user_id>')
def api_user_recent_rentals(user_id):
    """API trả về 100 số thuê gần nhất của một user"""
    with app.app_context():
        # Tìm user trong database
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Lấy 100 rental gần nhất của user
        recent_rentals = Rental.query.filter_by(
            user_id=user.id
        ).order_by(
            Rental.created_at.desc()
        ).limit(100).all()
        
        result = []
        for r in recent_rentals:
            result.append({
                'id': r.id,
                'phone': r.phone_number,
                'service': r.service_name,
                'price': r.price_charged,
                'status': r.status,
                'otp': r.otp_code,
                'otp_id': r.otp_id,
                'sim_id': r.sim_id,
                'created_at': r.created_at.strftime('%H:%M:%S %d/%m/%Y'),
                'expires_at': r.expires_at.strftime('%H:%M:%S %d/%m/%Y') if r.expires_at else None,
                'refunded': r.refunded,
                'refund_amount': r.refund_amount
            })
        
        return jsonify({
            'user_id': user.user_id,
            'username': user.username,
            'total_rentals': user.total_rentals,
            'recent_rentals': result
        })


@app.route('/user/<int:user_id>')
def user_detail(user_id):
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first_or_404()
        rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).all()
        if not rentals:
            rentals = Rental.query.filter_by(user_id=user_id).order_by(Rental.created_at.desc()).all()
        transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).all()
        
        profit = sum(r.price_charged - (r.cost or 0) for r in rentals if r.status == 'success')
        
        print(f"\n🔍 USER DETAIL: {user_id}")
        print(f"  - DB ID: {user.id}")
        print(f"  - Rentals found: {len(rentals)}")
        
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
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', USER_DETAIL_TEMPLATE),
        user=user_data, rentals=rentals, transactions=transactions, now=datetime.now()
    )

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
        rentals = Rental.query.filter(
            Rental.status == 'success',
            Rental.created_at >= start,
            Rental.created_at < end
        ).all()
        
        total_revenue = sum(r.price_charged for r in rentals)
        total_cost = sum(r.cost or 0 for r in rentals)
        net_profit = total_revenue - total_cost
        profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        service_stats = defaultdict(lambda: {'count': 0, 'revenue': 0, 'cost': 0})
        for r in rentals:
            service_stats[r.service_name]['count'] += 1
            service_stats[r.service_name]['revenue'] += r.price_charged
            service_stats[r.service_name]['cost'] += r.cost or 0
        
        by_service = []
        for name, data in service_stats.items():
            p = data['revenue'] - data['cost']
            margin = (p / data['revenue'] * 100) if data['revenue'] > 0 else 0
            by_service.append({
                'name': name,
                'count': data['count'],
                'revenue': data['revenue'],
                'cost': data['cost'],
                'profit': p,
                'margin': margin
            })
        
        profit_data = {
            'total_revenue': total_revenue,
            'total_cost': total_cost,
            'net_profit': net_profit,
            'profit_margin': profit_margin,
            'by_service': sorted(by_service, key=lambda x: x['profit'], reverse=True)
        }
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', PROFIT_TEMPLATE),
        profit=profit_data, period=period, now=now
    )

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
            trans = Transaction.query.filter(
                Transaction.description.like('%trừ tiền%') | Transaction.description.like('%Trừ tiền%')
            ).order_by(Transaction.created_at.desc()).limit(200).all()
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
            profit = r.price_charged - (r.cost or 0)
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
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', TRANSACTIONS_TEMPLATE),
        transactions=transactions_list, tab=tab, now=datetime.now()
    )

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
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', STATISTICS_TEMPLATE),
        stats_data=stats_data, stat_type=stat_type, now=now
    )

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
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', MANUAL_TEMPLATE),
        manual_trans=manual_list, now=datetime.now()
    )

@app.route('/broadcast')
def broadcast():
    with app.app_context():
        total_users = User.query.count()
        broadcast_logs = []
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', BROADCAST_TEMPLATE),
        total_users=total_users, broadcast_logs=broadcast_logs, now=datetime.now()
    )

@app.route('/deduct')
def deduct():
    return redirect(url_for('manual'))
@app.route('/api/get-all-users', methods=['GET'])
def api_get_all_users():
    """API cho SePay lấy danh sách users"""
    with app.app_context():
        users = User.query.all()
        result = []
        for u in users:
            result.append({
                'user_id': u.user_id,
                'balance': u.balance,
                'username': u.username,
                'last_active': u.last_active.isoformat() if u.last_active else None
            })
        return jsonify(result)

@app.route('/api/receive-sync', methods=['POST'])
def api_receive_sync():
    """Nhận đồng bộ từ SePay"""
    try:
        data = request.json
        sync_type = data.get('type')
        
        if sync_type == 'sepay_transaction':
            # Có giao dịch từ SePay
            tx_data = data.get('data', {})
            user_id = tx_data.get('user_id')
            amount = tx_data.get('amount')
            tx_code = tx_data.get('transaction_code')
            
            logger.info(f"📥 Nhận đồng bộ từ SePay: +{amount}đ cho user {user_id}")
            
            with app.app_context():
                user = User.query.filter_by(user_id=user_id).first()
                if user:

                    # 🔴 KIỂM TRA TRÁNH CỘNG TRÙNG
                    existing_tx = Transaction.query.filter_by(transaction_code=tx_code).first()
                    if existing_tx:
                        logger.info(f"⚠️ Transaction {tx_code} đã tồn tại, bỏ qua")
                        return jsonify({'success': True})

                    old_balance = user.balance

                    # 🔴 CHỈ CỘNG KHI AMOUNT > 0
                    if amount and amount > 0:
                        user.balance += amount
                    
                    # Tạo transaction record
                    transaction = Transaction(
                        user_id=user.id,
                        amount=amount,
                        type='deposit',
                        status='success',
                        transaction_code=tx_code,
                        description=f"Đồng bộ từ SePay",
                        created_at=datetime.now()
                    )

                    db.session.add(transaction)
                    db.session.commit()
                    
                    logger.info(f"✅ Cập nhật local từ SePay: {old_balance} → {user.balance}")
                    
                    # Cập nhật UI real-time (nếu dùng WebSocket)
                    # emit_balance_update(user_id, user.balance)
                    
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"❌ Lỗi receive_sync: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/add_money', methods=['POST'])
def add_money():
    user_id = request.form.get('user_id', type=int)
    amount = request.form.get('amount', type=int)
    reason = request.form.get('reason', 'Cộng tiền thủ công')
    
    print(f"\n🔍 DEBUG - Cộng tiền thủ công:")
    print(f"  User ID: {user_id}")
    print(f"  Amount: {amount}đ")
    print(f"  Reason: {reason}")
    
    if not user_id or not amount or amount < 1000:
        return jsonify({'success': False, 'error': 'Thông tin không hợp lệ'})
    
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'success': False, 'error': f'Không tìm thấy user {user_id}'})
        
        old_balance = user.balance
        new_balance = old_balance + amount
        
        # ===== BƯỚC 1: CẬP NHẬT LOCAL NGAY =====
        user.balance = new_balance
        
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
        
        logger.info(f"✅ LOCAL UPDATE: User {user_id}: {old_balance}đ → {new_balance}đ")
        
        # ===== BƯỚC 2: PUSH LÊN RENDER VỚI TRANSACTIONS =====
        RENDER_URL = "https://bot-thue-sms-new.onrender.com"
        push_data = {
            'user_id': user.user_id,
            'balance': user.balance,
            'username': user.username or f"user_{user.user_id}",
            'local_transactions': [
                {
                    'code': transaction_code,
                    'amount': amount,
                    'user_id': user.user_id,
                    'username': user.username or f"user_{user.user_id}",
                    'status': 'success'
                }
            ]
        }
        
        push_success = False
        logger.info(f"📤 Đang push lên Render với {len(push_data['local_transactions'])} transaction...")
        
        # Thử push 5 lần với exponential backoff
        for attempt in range(5):
            try:
                response = requests.post(
                    f"{RENDER_URL}/api/sync-bidirectional",
                    json=push_data,
                    timeout=5
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('skipped'):
                        logger.warning(f"⚠️ Push lần {attempt+1} bị skipped")
                    else:
                        push_success = True
                        logger.info(f"📤 Push lên Render thành công lần {attempt+1}")
                        logger.info(f"   Synced: {data.get('synced_from_local', 0)} transactions")
                        break
                else:
                    logger.warning(f"⚠️ Push lần {attempt+1} thất bại: {response.status_code}")
                    if attempt < 4:
                        time.sleep(2 ** attempt)  # 1,2,4,8 giây
                        
            except requests.exceptions.Timeout:
                logger.error(f"⏰ Timeout lần {attempt+1}")
                if attempt < 4:
                    time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"❌ Lỗi push lần {attempt+1}: {e}")
                if attempt < 4:
                    time.sleep(2 ** attempt)
        
        if not push_success:
            # Lưu vào file để retry sau
            save_failed_push(user.user_id, user.balance, user.username, transaction_code, amount)
            logger.error(f"❌ Push thất bại sau 5 lần - Đã lưu để retry")
        
        # Gửi Telegram
        message = (
            f"💰 *NẠP TIỀN THÀNH CÔNG!*\n\n"
            f"• *Số tiền:* +{amount:,}đ\n"
            f"• *Mã GD:* `{transaction_code}`\n"
            f"• *Số dư mới:* {user.balance:,}đ\n"
            f"• *Lý do:* {reason}"
        )
        send_telegram_notification(user.user_id, message)
        
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
        new_balance = old_balance - amount
        
        # ===== BƯỚC 1: CẬP NHẬT LOCAL NGAY =====
        user.balance = new_balance
        
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
        
        logger.info(f"✅ LOCAL UPDATE: User {user_id}: {old_balance}đ → {new_balance}đ")
        
        # ===== BƯỚC 2: PUSH LÊN RENDER VỚI TRANSACTIONS =====
        RENDER_URL = "https://bot-thue-sms-new.onrender.com"
        push_data = {
            'user_id': user.user_id,
            'balance': user.balance,
            'username': user.username or f"user_{user.user_id}",
            'local_transactions': [
                {
                    'code': transaction_code,
                    'amount': amount,
                    'user_id': user.user_id,
                    'username': user.username or f"user_{user.user_id}",
                    'status': 'success'
                }
            ]
        }
        
        push_success = False
        logger.info(f"📤 Đang push lên Render với {len(push_data['local_transactions'])} transaction...")
        
        # Thử push 5 lần với exponential backoff
        for attempt in range(5):
            try:
                response = requests.post(
                    f"{RENDER_URL}/api/sync-bidirectional",
                    json=push_data,
                    timeout=5
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('skipped'):
                        logger.warning(f"⚠️ Push lần {attempt+1} bị skipped")
                    else:
                        push_success = True
                        logger.info(f"📤 Push lên Render thành công lần {attempt+1}")
                        logger.info(f"   Synced: {data.get('synced_from_local', 0)} transactions")
                        break
                else:
                    logger.warning(f"⚠️ Push lần {attempt+1} thất bại: {response.status_code}")
                    if attempt < 4:
                        time.sleep(2 ** attempt)
                        
            except requests.exceptions.Timeout:
                logger.error(f"⏰ Timeout lần {attempt+1}")
                if attempt < 4:
                    time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"❌ Lỗi push lần {attempt+1}: {e}")
                if attempt < 4:
                    time.sleep(2 ** attempt)
        
        if not push_success:
            # Lưu vào file để retry sau
            save_failed_push(user.user_id, user.balance, user.username, transaction_code, amount)
            logger.error(f"❌ Push thất bại sau 5 lần - Đã lưu để retry")
        
        # Gửi Telegram
        message = (
            f"💸 *TRỪ TIỀN THỦ CÔNG*\n\n"
            f"• *Số tiền:* -{amount:,}đ\n"
            f"• *Mã GD:* `{transaction_code}`\n"
            f"• *Số dư mới:* {user.balance:,}đ\n"
            f"• *Lý do:* {reason}"
        )
        send_telegram_notification(user.user_id, message)
        
        return jsonify({'success': True, 'new_balance': user.balance})

# ===== THÊM ROUTE KIỂM TRA ĐỒNG BỘ =====
@app.route('/sync-status')
def sync_status():
    """Trang kiểm tra trạng thái đồng bộ"""
    return render_template_string('''
    <div class="card mt-4">
        <div class="card-header bg-info text-white">
            <h5><i class="bi bi-arrow-repeat"></i> Trạng thái đồng bộ</h5>
        </div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-6">
                    <h6>Kết nối SePay</h6>
                    <div id="sepay-status">Đang kiểm tra...</div>
                </div> 
                <div class="col-md-6">
                    <h6>Kết nối Render</h6>
                    <div id="render-status">Đang kiểm tra...</div>
                </div>
            </div>
            <button class="btn btn-primary mt-3" onclick="checkSync()">
                <i class="bi bi-arrow-repeat"></i> Kiểm tra lại
            </button>
        </div>
    </div>
    
    <script>
    function checkSync() {
        fetch('/api/check-sync')
            .then(r => r.json())
            .then(data => {
                document.getElementById('sepay-status').innerHTML = 
                    data.sepay ? '✅ Kết nối tốt' : '❌ Mất kết nối';
                document.getElementById('render-status').innerHTML = 
                    data.render ? '✅ Kết nối tốt' : '❌ Mất kết nối';
            });
    }
    checkSync();
    setInterval(checkSync, 30000);
    </script>
    ''')

@app.route('/send_message', methods=['POST'])
def send_message():
    user_id = request.form.get('user_id', type=int)
    message = request.form.get('message', '').strip()
    
    if not user_id or not message:
        return jsonify({'success': False, 'error': 'Thiếu thông tin'})
    
    success = send_telegram_notification(user_id, message)
    return jsonify({'success': success})

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)