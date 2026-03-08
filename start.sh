#!/bin/bash
# T?o file .env t? bi?n m?i tr??ng
echo "BOT_TOKEN=$BOT_TOKEN" > .env
echo "API_KEY=$API_KEY" >> .env
echo "BASE_URL=$BASE_URL" >> .env
echo "DATABASE_URL=$DATABASE_URL" >> .env
echo "ADMIN_ID=$ADMIN_ID" >> .env
echo "MB_ACCOUNT=$MB_ACCOUNT" >> .env
echo "MB_NAME=$MB_NAME" >> .env
echo "MB_BIN=$MB_BIN" >> .env
echo "SEPAY_TOKEN=$SEPAY_TOKEN" >> .env

# Hi?n th? n?i dung ?? ki?m tra
echo "=== N?I DUNG FILE .ENV ==="
cat .env
echo "=========================="

# Ch?y bot
python bot_railway.py
