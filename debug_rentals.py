import sqlite3
import os
from datetime import datetime

db_path = os.path.join('database', 'bot.db')
print(f"📁 Database path: {db_path}")
print("="*60)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Kiểm tra bảng rentals có tồn tại không
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rentals'")
if cursor.fetchone():
    print("✅ Bảng 'rentals' tồn tại")
else:
    print("❌ Bảng 'rentals' KHÔNG tồn tại!")
    conn.close()
    exit()

# 2. Xem cấu trúc bảng
cursor.execute("PRAGMA table_info(rentals)")
columns = cursor.fetchall()
print("\n📋 Cấu trúc bảng rentals:")
for col in columns:
    print(f"  - {col[1]} ({col[2]})")

# 3. Đếm tổng số records
cursor.execute("SELECT COUNT(*) FROM rentals")
total = cursor.fetchone()[0]
print(f"\n📊 Tổng số records: {total}")

if total == 0:
    print("❌ Bảng rentals trống! Chưa có dữ liệu thuê số.")
    conn.close()
    exit()

# 4. Lấy 5 records gần nhất
cursor.execute("""
    SELECT r.id, r.user_id, u.user_id as telegram_id, u.username, 
           r.service_name, r.phone_number, r.price_charged, r.status, r.created_at
    FROM rentals r
    LEFT JOIN users u ON r.user_id = u.id
    ORDER BY r.created_at DESC
    LIMIT 5
""")
recent = cursor.fetchall()

print("\n📱 5 rentals gần nhất:")
for r in recent:
    print(f"\n  ID: {r[0]}")
    print(f"  DB user_id: {r[1]}")
    print(f"  Telegram ID: {r[2]}")
    print(f"  Username: {r[3]}")
    print(f"  Service: {r[4]}")
    print(f"  Phone: {r[5]}")
    print(f"  Price: {r[6]}đ")
    print(f"  Status: {r[7]}")
    print(f"  Created: {r[8]}")

# 5. Kiểm tra user cụ thể 5180190297
telegram_id = 5180190297
cursor.execute("SELECT id FROM users WHERE user_id = ?", (telegram_id,))
user_row = cursor.fetchone()

if user_row:
    user_db_id = user_row[0]
    print(f"\n🔍 Kiểm tra user {telegram_id} (DB ID: {user_db_id})")
    
    cursor.execute("SELECT COUNT(*) FROM rentals WHERE user_id = ?", (user_db_id,))
    count = cursor.fetchone()[0]
    print(f"  Số rentals: {count}")
    
    if count > 0:
        cursor.execute("""
            SELECT service_name, phone_number, price_charged, status, created_at
            FROM rentals 
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_db_id,))
        user_rentals = cursor.fetchall()
        for r in user_rentals:
            print(f"    - {r[4]}: {r[0]} - {r[1]} - {r[2]}đ - {r[3]}")
    else:
        print("  ❌ KHÔNG CÓ RENTAL NÀO!")
        
        # Kiểm tra tất cả rentals để xem user_id mapping
        cursor.execute("SELECT DISTINCT user_id FROM rentals")
        all_user_ids = cursor.fetchall()
        print(f"\n📋 Các user_id trong rentals: {[u[0] for u in all_user_ids]}")
else:
    print(f"\n❌ Không tìm thấy user {telegram_id}")

conn.close()