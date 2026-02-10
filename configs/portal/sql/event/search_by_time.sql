SELECT *
FROM event
WHERE date_detection BETWEEN %(date_from)s AND %(date_to)s
ORDER BY date_detection DESC;
