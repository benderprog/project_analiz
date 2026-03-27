select
  p.pu_id,
  p.short_name,
  p.full_name
from classifier.pu p
order by p.short_name, p.full_name;
