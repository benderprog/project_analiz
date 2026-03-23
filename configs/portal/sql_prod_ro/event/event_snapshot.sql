with journal as (
  select
    j.s_id as event_id,
    j.date_detection,
    j.find_subdivision_unit_id,
    j.event_type_id
  from resource.border_event_new j
  where j.s_id = %(event_id)s
)
select distinct
  j.event_id,
  j.date_detection,
  j.find_subdivision_unit_id as subdivision_id,
  coalesce(type_event.name, '') as event_type,
  coalesce(classifier_dap.name, ud_class.article, '') as article_of_law
from journal j
left join classifier."classifier_52a43cc8-3d87-4f22-abd4-70d99cb15dd0" type_event
  on type_event.s_id = j.event_type_id
left join resource.violation violation
  on violation.event_id = j.event_id
left join resource.violator_violate_id_violation_s_id vi_to_vi
  on vi_to_vi.violation_id = violation.s_id
left join resource.involvement_offender involvement_offender
  on involvement_offender.violator_id = vi_to_vi.violator_id
left join resource.qualifications qualifications
  on qualifications.s_id = involvement_offender.qualification_id
left join classifier."classifier_4ff96fae-2376-4a4c-904e-bcf4260a2017" classifier_dap
  on classifier_dap.s_id = qualifications.qualifying_offense
left join resource.kusp kusp
  on kusp.violation_id = violation.s_id
left join resource.qualification_offence qualification_offence
  on qualification_offence.kusp_id = kusp.s_id
left join classifier."classifier_f9c9df5e-6b37-42d6-a2f5-bba85c368ebc" ud_class
  on ud_class.s_id = qualification_offence.qualification_offence_id;
