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

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Cấu hình database
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'bot.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# API Configuration (giữ nguyên)
API_KEY = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ6emxhbXp6MTEyMiIsImp0aSI6IjgwNTYwIiwiaWF0IjoxNzYxNjEyODAzLCJleHAiOjE4MjM4MjA4MDN9.4u-0IEkd2dgB6QtLEMlgp0KG55JwDDfMiNd98BQNzuJljOA9UTDymPsqnheIqGFM7WVGx94iV71tZasx62JIvw"
BASE_URL = "https://apisim.codesim.net"

# ====================== BASE TEMPLATE - SIÊU CHUYÊN NGHIỆP (đã xóa Nạp Web & API) ======================
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
    </style>
</head>
<body>
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
                    <li class="nav-item"><a class="nav-link px-4" href="/statistics"><i class="bi bi-bar-chart-line"></i> Thống kê</a></li>
                    <li class="nav-item"><span class="nav-link text-white-50"><i class="bi bi-clock-history me-1"></i>{{ now.strftime('%H:%M %d/%m/%Y') }}</span></li>
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
            $('.table').DataTable({
                language: { url: '//cdn.datatables.net/plug-ins/1.13.7/i18n/vi.json' },
                pageLength: 15,
                responsive: true,
                order: [[0, 'desc']]
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
        <table class="table table-hover mb-0">
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
        <button class="btn btn-success" onclick="exportToExcel()"><i class="bi bi-file-earmark-excel"></i> Xuất Excel toàn bộ</button>
    </div>
    <div class="card-body">
        <input type="text" id="searchInput" class="search-box mb-4 w-100" placeholder="🔍 Tìm kiếm User ID, Username, Số dư...">
        <table id="usersTable" class="table table-striped table-hover">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>User ID</th>
                    <th>Username</th>
                    <th>Số dư</th>
                    <th>Đã thuê</th>
                    <th>Tổng chi</th>
                    <th>Lợi nhuận từ user</th>
                    <th>Ngày tạo</th>
                    <th>Trạng thái</th>
                    <th>Thao tác</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td>{{ user.id }}</td>
                    <td><code>{{ user.user_id }}</code></td>
                    <td>@{{ user.username or 'N/A' }}</td>
                    <td class="fw-bold text-success">{{ "{:,.0f}".format(user.balance) }}đ</td>
                    <td>{{ user.total_rentals }}</td>
                    <td>{{ "{:,.0f}".format(user.total_spent) }}đ</td>
                    <td class="text-success fw-bold">{{ "{:,.0f}".format(user.profit or 0) }}đ</td>
                    <td>{{ user.created_at.strftime('%d/%m/%Y %H:%M') }}</td>
                    <td><span class="badge bg-{{ 'danger' if user.is_banned else 'success' }}">{{ 'Bị khóa' if user.is_banned else 'Hoạt động' }}</span></td>
                    <td>
                        <button class="btn btn-sm btn-primary" onclick="addMoney({{ user.user_id }})"><i class="bi bi-plus-circle"></i></button>
                        <button class="btn btn-sm btn-{{ 'success' if user.is_banned else 'danger' }}" onclick="toggleBan({{ user.user_id }})"><i class="bi bi-{{ 'unlock' if user.is_banned else 'lock' }}"></i></button>
                        <a href="/user/{{ user.user_id }}" class="btn btn-sm btn-info text-white"><i class="bi bi-eye-fill"></i> Chi tiết đầy đủ</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<div class="modal fade" id="addMoneyModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <div class="modal-header"><h5 class="modal-title">Cộng tiền thủ công</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
            <form id="addMoneyForm">
                <div class="modal-body">
                    <input type="hidden" name="user_id" id="modal_user_id">
                    <div class="mb-3"><label class="form-label">Số tiền (VNĐ)</label><input type="number" class="form-control" name="amount" min="1000" step="1000" required></div>
                    <div class="mb-3"><label class="form-label">Lý do</label><input type="text" class="form-control" name="reason" value="Cộng tiền thủ công"></div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                    <button type="submit" class="btn btn-primary">Xác nhận cộng tiền</button>
                </div>
            </form>
        </div>
    </div>
</div>

<script>
function addMoney(userId) { 
    document.getElementById('modal_user_id').value = userId; 
    new bootstrap.Modal(document.getElementById('addMoneyModal')).show(); 
}
document.getElementById('addMoneyForm').addEventListener('submit', function(e) {
    e.preventDefault();
    fetch('/add_money', {method: 'POST', body: new URLSearchParams(new FormData(this))})
    .then(() => location.reload());
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
        <table id="profitTable" class="table table-striped">
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
            <li class="nav-item"><a class="nav-link {% if tab == 'manual' %}active{% endif %}" href="?tab=manual">Cộng thủ công</a></li>
        </ul>
        <table id="transTable" class="table table-striped">
            <thead><tr><th>Thời gian</th><th>User ID</th><th>Loại</th><th>Dịch vụ</th><th>Số tiền</th><th>Lợi nhuận</th><th>Mã GD</th><th>Trạng thái</th></tr></thead>
            <tbody>
                {% for trans in transactions %}
                <tr>
                    <td>{{ trans.time }}</td>
                    <td><code>{{ trans.user_id }}</code></td>
                    <td><span class="badge bg-{{ 'success' if trans.type == 'deposit' else 'primary' }}">{{ 'Nạp tiền' if trans.type == 'deposit' else 'Thuê số' }}</span></td>
                    <td>{{ trans.service or '—' }}</td>
                    <td class="fw-bold">{{ "{:,.0f}".format(trans.amount) }}đ</td>
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
<div class="row justify-content-center">
    <div class="col-lg-7">
        <div class="card">
            <div class="card-header"><h5><i class="bi bi-plus-circle-fill"></i> Cộng tiền thủ công cho user</h5></div>
            <div class="card-body">
                <form method="POST" action="/add_money">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label">User ID (Telegram ID)</label>
                            <input type="number" class="form-control" name="user_id" required placeholder="5180190297">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label">Số tiền (VNĐ)</label>
                            <input type="number" class="form-control" name="amount" min="1000" step="1000" required>
                        </div>
                    </div>
                    <div class="mt-3">
                        <label class="form-label">Lý do cộng tiền</label>
                        <input type="text" class="form-control" name="reason" value="Cộng tiền thủ công">
                    </div>
                    <button type="submit" class="btn btn-primary w-100 mt-4 py-3 fs-5"><i class="bi bi-check-circle"></i> XÁC NHẬN CỘNG TIỀN</button>
                </form>
            </div>
        </div>
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
        <table class="table table-striped">
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

# ====================== USER DETAIL TEMPLATE (SIÊU CHI TIẾT) ======================
USER_DETAIL_TEMPLATE = '''
<div class="card">
    <div class="card-header d-flex justify-content-between">
        <h5><i class="bi bi-person-fill"></i> CHI TIẾT USER #{{ user.user_id }}</h5>
        <a href="/users" class="btn btn-secondary"><i class="bi bi-arrow-left"></i> Quay lại danh sách</a>
    </div>
    <div class="card-body">
        <div class="row">
            <div class="col-md-4">
                <div class="card h-100">
                    <div class="card-header"><h6>Thông tin cơ bản</h6></div>
                    <div class="card-body">
                        <ul class="list-group list-group-flush">
                            <li class="list-group-item"><strong>Username:</strong> @{{ user.username or 'Chưa cập nhật' }}</li>
                            <li class="list-group-item"><strong>Số dư hiện tại:</strong> <span class="text-success fw-bold fs-5">{{ "{:,.0f}".format(user.balance) }}đ</span></li>
                            <li class="list-group-item"><strong>Tổng số lần thuê:</strong> {{ user.total_rentals }} lần</li>
                            <li class="list-group-item"><strong>Tổng chi tiêu:</strong> {{ "{:,.0f}".format(user.total_spent) }}đ</li>
                            <li class="list-group-item"><strong>Lợi nhuận mang lại:</strong> <span class="text-success fw-bold">{{ "{:,.0f}".format(user.profit) }}đ</span></li>
                            <li class="list-group-item"><strong>Trạng thái:</strong> <span class="badge bg-{{ 'success' if not user.is_banned else 'danger' }}">{{ 'Hoạt động' if not user.is_banned else 'Đã bị khóa' }}</span></li>
                            <li class="list-group-item"><strong>Ngày tham gia:</strong> {{ user.created_at.strftime('%d/%m/%Y %H:%M') }}</li>
                        </ul>
                    </div>
                </div>
            </div>
            <div class="col-md-8">
                <ul class="nav nav-tabs" id="userTab" role="tablist">
                    <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#rentalsTab">Thuê số ({{ rentals|length }})</a></li>
                    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#transactionsTab">Giao dịch tiền</a></li>
                </ul>
                <div class="tab-content mt-3">
                    <div class="tab-pane fade show active" id="rentalsTab">
                        <table class="table table-striped" id="rentalDetailTable">
                            <thead><tr><th>Thời gian</th><th>Dịch vụ</th><th>SĐT</th><th>Giá thu khách</th><th>Chi phí API</th><th>Lợi nhuận</th><th>Trạng thái</th></tr></thead>
                            <tbody>
                                {% for r in rentals %}
                                <tr>
                                    <td>{{ r.created_at.strftime('%d/%m/%Y %H:%M') }}</td>
                                    <td>{{ r.service_name }}</td>
                                    <td><code>{{ r.phone or '—' }}</code></td>
                                    <td>{{ "{:,.0f}".format(r.price_charged) }}đ</td>
                                    <td>{{ "{:,.0f}".format(r.cost or 0) }}đ</td>
                                    <td class="text-success">{{ "{:,.0f}".format(r.price_charged - (r.cost or r.price_charged - 1000)) }}đ</td>
                                    <td><span class="status-{{ 'success' if r.status == 'success' else 'cancel' }}">{{ 'ĐÃ THUÊ' if r.status == 'success' else 'ĐÃ HỦY' }}</span></td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    <div class="tab-pane fade" id="transactionsTab">
                        <table class="table table-striped" id="transDetailTable">
                            <thead><tr><th>Thời gian</th><th>Loại</th><th>Số tiền</th><th>Mã giao dịch</th><th>Ghi chú</th></tr></thead>
                            <tbody>
                                {% for t in transactions %}
                                <tr>
                                    <td>{{ t.created_at.strftime('%d/%m/%Y %H:%M') }}</td>
                                    <td><span class="badge bg-success">NẠP TIỀN</span></td>
                                    <td class="text-success fw-bold">+{{ "{:,.0f}".format(t.amount) }}đ</td>
                                    <td><code>{{ t.transaction_code }}</code></td>
                                    <td>{{ t.description or '—' }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
'''

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
                recent.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': item.user_id,
                    'type': 'Nạp tiền',
                    'service': None,
                    'amount': item.amount,
                    'profit': 0
                })
            else:
                p = item.price_charged - (item.cost or (item.price_charged - 1000))
                recent.append({
                    'time': item.created_at.strftime('%H:%M %d/%m'),
                    'user_id': item.user_id,
                    'type': 'Thuê số',
                    'service': item.service_name,
                    'amount': item.price_charged,
                    'profit': p
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
            profit = sum(r.price_charged - (r.cost or (r.price_charged - 1000)) for r in user_rentals)
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

@app.route('/user/<int:user_id>')
def user_detail(user_id):
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first_or_404()
        rentals = Rental.query.filter_by(user_id=user.id).order_by(Rental.created_at.desc()).all()
        transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).all()
        
        profit = sum(r.price_charged - (r.cost or (r.price_charged - 1000)) for r in rentals if r.status == 'success')
        
        user_data = {
            'user_id': user.user_id,
            'username': user.username,
            'balance': user.balance,
            'total_rentals': user.total_rentals,
            'total_spent': user.total_spent,
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
        total_cost = sum(r.cost or (r.price_charged - 1000) for r in rentals)
        net_profit = total_revenue - total_cost
        profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        service_stats = defaultdict(lambda: {'count': 0, 'revenue': 0, 'cost': 0})
        for r in rentals:
            service_stats[r.service_name]['count'] += 1
            service_stats[r.service_name]['revenue'] += r.price_charged
            service_stats[r.service_name]['cost'] += r.cost or (r.price_charged - 1000)
        
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
        elif tab == 'manual':
            trans = Transaction.query.filter(Transaction.description.like('%thủ công%')).order_by(Transaction.created_at.desc()).limit(200).all()
            rentals = []
        else:
            trans = Transaction.query.order_by(Transaction.created_at.desc()).limit(100).all()
            rentals = Rental.query.order_by(Rental.created_at.desc()).limit(100).all()
        
        transactions_list = []
        for t in trans:
            transactions_list.append({
                'time': t.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': t.user_id,
                'type': 'deposit',
                'service': None,
                'amount': t.amount,
                'profit': 0,
                'code': t.transaction_code,
                'status': t.status
            })
        for r in rentals:
            profit = r.price_charged - (r.cost or (r.price_charged - 1000))
            code = getattr(r, 'transaction_code', f"RENTAL_{r.id}_{r.created_at.strftime('%Y%m%d%H%M%S')}")
            transactions_list.append({
                'time': r.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': r.user_id,
                'type': 'rental',
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
                cost = sum(r.cost or (r.price_charged - 1000) for r in rentals)
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
                cost = sum(r.cost or (r.price_charged - 1000) for r in rentals)
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
            Transaction.description.like('%thủ công%')
        ).order_by(Transaction.created_at.desc()).limit(15).all()
        
        manual_list = []
        for t in manual_trans:
            user = User.query.get(t.user_id)
            manual_list.append({
                'time': t.created_at.strftime('%H:%M %d/%m/%Y'),
                'user_id': user.user_id if user else 'N/A',
                'amount': t.amount,
                'reason': t.description
            })
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', MANUAL_TEMPLATE),
        now=datetime.now()
    )

@app.route('/add_money', methods=['POST'])
def add_money():
    user_id = request.form.get('user_id', type=int)
    amount = request.form.get('amount', type=int)
    reason = request.form.get('reason', 'Cộng tiền thủ công')
    
    if not user_id or not amount or amount < 1000:
        flash('Vui lòng nhập đầy đủ thông tin hợp lệ!', 'danger')
        return redirect(url_for('manual'))
    
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if not user:
            flash(f'Không tìm thấy user ID {user_id}', 'danger')
            return redirect(url_for('manual'))
        
        old_balance = user.balance
        user.balance += amount
        
        transaction_code = f"MANUAL_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            type='deposit',
            status='success',
            transaction_code=transaction_code,
            description=reason,
            created_at=datetime.now()
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        # Gửi thông báo Telegram (nếu có BOT_TOKEN)
        try:
            BOT_TOKEN = os.getenv('BOT_TOKEN')
            if BOT_TOKEN:
                telegram_message = (
                    f"💰 *NẠP TIỀN THÀNH CÔNG!*\n\n"
                    f"• *Số tiền:* {amount:,}đ\n"
                    f"• *Mã GD:* {transaction_code}\n"
                    f"• *Số dư mới:* {user.balance:,}đ\n"
                    f"• *Thời gian:* {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
                )
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={'chat_id': user.user_id, 'text': telegram_message, 'parse_mode': 'Markdown'},
                    timeout=5
                )
        except Exception as e:
            logger.error(f"Lỗi gửi Telegram: {e}")
        
        flash(f'✅ CỘNG TIỀN THÀNH CÔNG!\n'
              f'• User: {user_id}\n'
              f'• Số tiền: {amount:,}đ\n'
              f'• Mã GD: {transaction_code}\n'
              f'• Số dư mới: {user.balance:,}đ', 'success')
    
    return redirect(url_for('manual'))

@app.route('/toggle_ban', methods=['POST'])
def toggle_ban():
    data = request.get_json()
    user_id = data.get('user_id')
    
    with app.app_context():
        user = User.query.filter_by(user_id=user_id).first()
        if user:
            user.is_banned = not user.is_banned
            db.session.commit()
            return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/export_users')
def export_users():
    with app.app_context():
        users = User.query.all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'User ID', 'Username', 'Số dư', 'Đã thuê', 'Tổng chi', 'Ngày tạo', 'Trạng thái'])
        
        for u in users:
            writer.writerow([
                u.id, u.user_id, u.username or '', 
                u.balance, u.total_rentals, u.total_spent, 
                u.created_at.strftime('%d/%m/%Y'), 
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