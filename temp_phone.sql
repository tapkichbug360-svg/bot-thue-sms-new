SELECT 
    r.id,
    r.user_id,
    u.user_id as telegram_id,
    u.username,
    r.service_name,
    r.status,
    r.otp_code,
    r.created_at,
    r.expires_at
FROM rentals r
LEFT JOIN users u ON r.user_id = u.id
WHERE r.phone_number = '0332496914'
ORDER BY r.created_at DESC;
