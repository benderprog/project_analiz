select
  s.s_id as subdivision_id,
  coalesce(s.name, s.short_name, '') as name,
  coalesce(s.short_name, '') as short_name,
  s.parent_id as parent_pu_id
from resource.subdivision_unit s
where (%(pu_id)s is null or s.parent_id = %(pu_id)s)
order by name;
