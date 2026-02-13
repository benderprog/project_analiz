select distinct
  o.event_id
from offenders o
where lower(o.second_name) = lower(%(second_name)s)
  and (
    (%(birth_date)s is not null and o.date_of_birth = %(birth_date)s)
    or (%(birth_date)s is null and %(birth_year)s is not null and extract(year from o.date_of_birth) = %(birth_year)s)
    or (%(birth_date)s is null and %(birth_year)s is null)
  )
order by o.event_id
limit %(limit)s;
