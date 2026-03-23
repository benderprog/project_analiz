select distinct
  e.event_id,
  e.date_detection,
  e.find_subdivision_unit_id as subdivision_id,
  e.event_type,
  e.article_of_law
from event e
join offenders o on o.event_id = e.event_id
where replace(lower(o.second_name), 'ё', 'е') = replace(lower(%(second_name)s), 'ё', 'е')
  and (
    (%(birth_date)s is not null and o.date_of_birth = %(birth_date)s::date)
    or (%(birth_date)s is null and %(birth_year)s is not null and extract(year from o.date_of_birth) = %(birth_year)s)
    or (%(birth_date)s is null and %(birth_year)s is null)
  )
order by e.date_detection desc
limit %(limit)s;
