import os
import sys
from datetime import datetime

# Thêm đường dẫn hiện tại vào sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

os.environ['DATABASE_URL'] = 'sqlite:///instance/database.db'

try:
    from database.models import User, Rental
    from bot import app
    
    print("=" * 60)
    print("TỔNG QUAN DATABASE")
    print("=" * 60)
    
    with app.app_context():
        # Thống kê user
        total_users = User.query.count()
        banned_users = User.query.filter_by(is_banned=True).count()
        total_balance = sum(u.balance for u in User.query.all())
        
        print(f"\n📊 USER STATISTICS:")
        print(f"   Tổng số user: {total_users}")
        print(f"   User bị banned: {banned_users}")
        print(f"   Tổng số dư: {total_balance:,}đ")
        print(f"   Số dư trung bình: {total_balance/total_users if total_users > 0 else 0:,.0f}đ")
        
        # 10 user gần nhất
        print(f"\n📋 10 USERS GẦN NHẤT:")
        users = User.query.order_by(User.created_at.desc()).limit(10).all()
        for u in users:
            print(f"   {u.user_id} | {u.username or 'None'} | {u.balance:,}đ | {u.created_at.strftime('%Y-%m-%d %H:%M')}")
        
        # Kiểm tra user 7601197096
        print(f"\n🔍 CHECK USER 7601197096:")
        user = User.query.filter_by(user_id=7601197096).first()
        if user:
            print(f"   ✅ TÌM THẤY!")
            print(f"   Username: {user.username}")
            print(f"   Balance: {user.balance:,}đ")
            print(f"   Created: {user.created_at}")
            print(f"   Banned: {user.is_banned}")
            print(f"   Total spent: {user.total_spent:,}đ")
            print(f"   Total rentals: {user.total_rentals}")
            
            rentals = Rental.query.filter_by(user_id=7601197096).all()
            print(f"   Số lần thuê: {len(rentals)}")
            if rentals:
                print(f"   Rental gần nhất: {rentals[0].created_at.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"   ❌ KHÔNG TÌM THẤY!")
            
        # Thống kê rental
        print(f"\n📊 RENTAL STATISTICS:")
        total_rentals = Rental.query.count()
        waiting = Rental.query.filter_by(status='waiting').count()
        completed = Rental.query.filter_by(status='completed').count()
        cancelled = Rental.query.filter_by(status='cancelled').count()
        expired = Rental.query.filter_by(status='expired').count()
        
        print(f"   Tổng số rental: {total_rentals}")
        print(f"   Đang chờ OTP: {waiting}")
        print(f"   Đã nhận OTP: {completed}")
        print(f"   Đã hủy: {cancelled}")
        print(f"   Hết hạn: {expired}")
        
        # Tổng doanh thu
        total_revenue = sum(r.price_charged for r in Rental.query.filter_by(status='completed').all())
        print(f"   Tổng doanh thu: {total_revenue:,}đ")
        
        # Top 10 user theo số dư
        print(f"\n🏆 TOP 10 USERS THEO SỐ DƯ:")
        top_users = User.query.order_by(User.balance.desc()).limit(10).all()
        for i, u in enumerate(top_users, 1):
            print(f"   {i}. {u.user_id} | {u.username or 'None'} | {u.balance:,}đ")
            
        # Top 10 user theo số lần thuê
        print(f"\n🏆 TOP 10 USERS THEO SỐ LẦN THUÊ:")
        from sqlalchemy import func
        top_rentals = db.session.query(
            Rental.user_id, 
            func.count(Rental.id).label('total_rentals'),
            func.sum(Rental.price_charged).label('total_spent')
        ).group_by(Rental.user_id).order_by(func.count(Rental.id).desc()).limit(10).all()
        
        for i, (user_id, count, spent) in enumerate(top_rentals, 1):
            user = User.query.get(user_id)
            username = user.username if user else 'Unknown'
            print(f"   {i}. {user_id} | {username} | {count} lần | {spent:,}đ")
            
        # Kiểm tra file log gần đây
        print(f"\n📝 KIỂM TRA LOG:")
        import glob
        log_files = glob.glob("*.log")
        if log_files:
            latest_log = max(log_files, key=os.path.getctime)
            print(f"   Log file gần nhất: {latest_log}")
            
            # Tìm user trong log
            import subprocess
            result = subprocess.run(['findstr', '/c:7601197096', latest_log], capture_output=True, text=True)
            if result.stdout:
                print(f"   ✅ Có log của user này trong {latest_log}")
                print(f"   {result.stdout.split(chr(10))[0][:100]}")
            else:
                print(f"   ❌ Không có log của user này trong {latest_log}")
        
except Exception as e:
    print(f"❌ LỖI: {e}")
    import traceback
    traceback.print_exc()
