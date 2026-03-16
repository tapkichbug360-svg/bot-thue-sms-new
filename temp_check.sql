SELECT 
    phone_number,
    service_name,
    status,
    otp_code,
    refunded,
    datetime(created_at,'localtime') as created,
    datetime(expires_at,'localtime') as expires
FROM rentals 
WHERE phone_number = '0325970916';
