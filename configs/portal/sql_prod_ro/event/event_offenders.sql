select distinct
  violator.s_id as offender_id,
  violation.event_id as event_id,
  coalesce(faces.surname_cyrillic, '') as second_name,
  coalesce(faces.name_cyrillic, '') as first_name,
  coalesce(faces.patronymic_cyrillic, '') as patronymic_name,
  faces.data_birth as date_of_birth
from resource.violation violation
join resource.violator_violate_id_violation_s_id vi_to_vi
  on vi_to_vi.violation_id = violation.s_id
join resource.violator violator
  on violator.s_id = vi_to_vi.violator_id
left join resource.violator_face_list_face_s_id viol_to_face
  on viol_to_face.violator_id = violator.s_id
left join resource.face faces
  on faces.s_id = viol_to_face.face_id
where violation.event_id = any(%(event_ids)s)
order by event_id, offender_id;
