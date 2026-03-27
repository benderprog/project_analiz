select
  e.event_id,
  e.date_detection,
  e.find_subdivision_unit_id as subdivision_id,
  e.event_type,
  e.article_of_law
from resource.event e
where e.date_detection between %(from_ts)s::timestamptz and %(to_ts)s::timestamptz
order by e.date_detection desc
limit %(limit)s;
