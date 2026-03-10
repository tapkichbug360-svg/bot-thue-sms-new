import requests, sqlite3

user_id = 6882881250

# Lấy từ Render
r = requests.post('https://bot-thue-sms-new.onrender.com/api/force-sync-user', 
                  json={'user_id': user_id})
data = r.json()
print(f'📊 Render balance: {data["balance"]}đ')

# Cập nhật local
conn = sqlite3.connect('database/bot.db')
cursor = conn.cursor()
cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', 
               (data['balance'], user_id))
conn.commit()
conn.close()
print('✅ Đã cập nhật local!')

# Kiểm tra lại
conn = sqlite3.connect('database/bot.db')
cursor = conn.cursor()
cursor.execute('SELECT balance FROM users WHERE user_id=?', (user_id,))
bal = cursor.fetchone()[0]
print(f'💰 User {user_id}: {bal}đ')
conn.close()
