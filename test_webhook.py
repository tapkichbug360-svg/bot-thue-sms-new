import requests
import json

# Dữ liệu webhook mẫu
data = {
    "transferType": "in",
    "accountNumber": "666666291005",
    "transferAmount": 20000,
    "content": "NAP ABC123",
    "transactionDate": "2024-01-01 12:00:00"
}

# Gửi request
url = "http://localhost:8080/webhook/sepay"
headers = {"Content-Type": "application/json"}

try:
    response = requests.post(url, json=data, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
