select
  e.event_id,
  e.date_detection,
  e.find_subdivision_unit_id as subdivision_id,
  e.event_type,
  e.article_of_law
from event e
where e.find_subdivision_unit_id = %(subdivision_id)s
  and e.date_detection between %(date_from)s and %(date_to)s
order by e.date_detection desc
limit %(limit)s;
