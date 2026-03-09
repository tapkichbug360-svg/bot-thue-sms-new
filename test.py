import sqlite3
import requests

print("="*50)
print("🔍 KIỂM TRA HỆ THỐNG NẠP TIỀN")
print("="*50)

# 1. Kiểm tra database local
conn = sqlite3.connect("database/bot.db")
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM transactions")
total = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM transactions WHERE status='success'")
success = cursor.fetchone()[0]
cursor.execute("SELECT user_id, balance FROM users WHERE user_id=6764756905")
user = cursor.fetchone()
conn.close()

print("\n📊 LOCAL DATABASE:")
print(f"   Tổng GD: {total}")
print(f"   Thành công: {success}")
if user:
    print(f"   User 6764756905: {user[1]}đ")
else:
    print("   User 6764756905: ❌ Không tồn tại")

# 2. Kiểm tra Render
try:
    r = requests.get("https://bot-thue-sms-v2.onrender.com/api/stats", timeout=5)
    if r.status_code == 200:
        data = r.json()
        print("\n🌐 RENDER SERVER: ✅ Online")
        print(f"   Stats: {data.get('stats', {})}")
    else:
        print(f"\n🌐 RENDER SERVER: ❌ Lỗi {r.status_code}")
except:
    print("\n🌐 RENDER SERVER: ❌ Không kết nối được")

# 3. Test gửi webhook
test_data = {
    "transferType": "in",
    "accountNumber": "666666291005",
    "transferAmount": 1000,
    "content": "NAP TEST",
    "transactionDate": "2024-01-01 12:00:00"
}

try:
    r = requests.post("http://localhost:8080/webhook/sepay", json=test_data, timeout=2)
    print("\n📨 WEBHOOK LOCAL: ✅ Gửi được (Status: {})".format(r.status_code))
except:
    print("\n📨 WEBHOOK LOCAL: ❌ Không gửi được (Bot local chưa chạy?)")

try:
    r = requests.post("https://bot-thue-sms-v2.onrender.com/webhook/sepay", json=test_data, timeout=2)
    print("📨 WEBHOOK RENDER: ✅ Gửi được (Status: {})".format(r.status_code))
except:
    print("📨 WEBHOOK RENDER: ❌ Không gửi được")

print("\n" + "="*50)
