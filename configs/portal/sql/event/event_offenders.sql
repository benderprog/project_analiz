SELECT *
FROM offender
WHERE event_id = %(event_id)s
ORDER BY offender_id;
