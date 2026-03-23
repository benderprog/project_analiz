select
  s.s_id as pu_id,
  coalesce(s.short_name, '') as short_name,
  coalesce(s.name, s.short_name, '') as full_name
from resource.subdivision_unit s
where s.parent_id is null
order by short_name, full_name;
