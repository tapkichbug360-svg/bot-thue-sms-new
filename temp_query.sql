    SELECT r.phone_number, r.service_name, r.status, r.otp_code, r.created_at
    FROM rentals r
    WHERE r.user_id = (SELECT id FROM users WHERE user_id = 5180190297)
    AND r.status = 'success'
    ORDER BY r.created_at DESC
    LIMIT 5;
