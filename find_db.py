import os
import sqlite3
from pathlib import Path

print("🔍 TÌM KIẾM DATABASE...")
print("=" * 60)

# Tìm tất cả file .db
db_files = list(Path('.').glob('**/*.db')) + list(Path('.').glob('**/*.sqlite'))

if not db_files:
    print("❌ Không tìm thấy file database nào!")
else:
    for db_file in db_files:
        size = db_file.stat().st_size
        print(f"\n📁 {db_file} ({size} bytes)")
        
        if size == 0:
            print("   ⚠️ File rỗng")
            continue
            
        try:
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            
            # Lấy danh sách bảng
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            if tables:
                print(f"   📋 Tables: {[t[0] for t in tables]}")
                
                # Kiểm tra bảng user
                if any(t[0] == 'user' for t in tables):
                    cursor.execute("SELECT COUNT(*) FROM user;")
                    count = cursor.fetchone()[0]
                    print(f"   👥 Total users: {count}")
                    
                    if count > 0:
                        cursor.execute("SELECT user_id, username, balance FROM user LIMIT 5;")
                        for row in cursor.fetchall():
                            print(f"      {row[0]} | {row[1] or 'None'} | {row[2]:,}đ")
                        
                        # Check user 7601197096
                        cursor.execute("SELECT * FROM user WHERE user_id = 7601197096;")
                        user = cursor.fetchone()
                        if user:
                            print(f"\n   ✅ TÌM THẤY USER 7601197096!")
                            print(f"      Username: {user[1]}")
                            print(f"      Balance: {user[2]:,}đ")
                            print(f"      Created: {user[4]}")
                        else:
                            print(f"\n   ❌ KHÔNG TÌM THẤY USER 7601197096")
                else:
                    print("   ⚠️ Không có bảng user")
            else:
                print("   📭 Database rỗng (không có bảng)")
                
            conn.close()
            
        except Exception as e:
            print(f"   ❌ Lỗi: {e}")

print("\n" + "=" * 60)
print("✅ Hoàn thành kiểm tra!")
