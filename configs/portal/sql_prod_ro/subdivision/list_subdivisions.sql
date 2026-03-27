select
  s.subdivision_id,
  s.name,
  s.short_name,
  s.parent_pu_id
from classifier.subdivision s
where (%(pu_id)s is null or s.parent_pu_id = %(pu_id)s)
order by s.name;
