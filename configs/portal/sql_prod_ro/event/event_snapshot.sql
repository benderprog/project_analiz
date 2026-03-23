select
  e.event_id,
  e.date_detection,
  e.find_subdivision_unit_id as subdivision_id,
  e.event_type,
  e.article_of_law
from event e
where e.event_id = %(event_id)s;
