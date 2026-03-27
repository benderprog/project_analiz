select
  o.offender_id,
  o.event_id,
  o.second_name,
  o.first_name,
  o.patronymic_name,
  o.date_of_birth
from resource.offenders o
where o.event_id = any(%(event_ids)s)
order by o.event_id, o.offender_id;
