SELECT *
FROM event
WHERE find_subdivision_unit_id = %(subdivision_id)s
  AND date_detection BETWEEN %(date_from)s AND %(date_to)s
ORDER BY date_detection DESC;
