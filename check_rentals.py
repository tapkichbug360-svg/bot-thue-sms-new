import sqlite3
import os

db_path = os.path.join('C:\\', 'bot_thue_sms_24h', 'database', 'bot.db')
print("="*60)
print("🔧 FIX RENTALS USER_ID")
print("="*60)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Kiểm tra user
telegram_id = 5180190297
cursor.execute("SELECT id FROM users WHERE user_id = ?", (telegram_id,))
result = cursor.fetchone()

if not result:
    print(f"❌ Không tìm thấy user {telegram_id}")
    conn.close()
    exit()

db_id = result[0]
print(f"✅ User {telegram_id} có DB ID: {db_id}")

# 2. Đếm số rentals sai
cursor.execute("SELECT COUNT(*) FROM rentals WHERE user_id = ?", (telegram_id,))
wrong_count = cursor.fetchone()[0]
print(f"📊 Số rentals đang dùng Telegram ID: {wrong_count}")

if wrong_count == 0:
    print("✅ Không có rentals nào cần fix!")
    conn.close()
    exit()

# 3. Xem mẫu rentals sai
cursor.execute("""
    SELECT id, service_name, phone_number, status 
    FROM rentals 
    WHERE user_id = ?
    LIMIT 3
""", (telegram_id,))

print("\n📋 Mẫu rentals sẽ được fix:")
for row in cursor.fetchall():
    print(f"  - ID: {row[0]}, Service: {row[1]}, Phone: {row[2]}, Status: {row[3]}")

# 4. Hỏi xác nhận
print(f"\n⚠️ Sẽ update {wrong_count} rentals từ user_id={telegram_id} thành {db_id}")
confirm = input("Tiếp tục? (y/n): ")

if confirm.lower() == 'y':
    # Update rentals
    cursor.execute("UPDATE rentals SET user_id = ? WHERE user_id = ?", (db_id, telegram_id))
    updated = cursor.rowcount
    conn.commit()
    print(f"✅ Đã cập nhật {updated} rentals thành công!")
    
    # Kiểm tra lại
    cursor.execute("SELECT COUNT(*) FROM rentals WHERE user_id = ?", (db_id,))
    correct_count = cursor.fetchone()[0]
    print(f"📊 Số rentals của user {db_id} sau khi fix: {correct_count}")
else:
    print("❌ Đã hủy!")

conn.close()
print("\n" + "="*60)
input("Nhấn Enter để thoát...")