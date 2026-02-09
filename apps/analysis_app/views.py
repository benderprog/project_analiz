from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.views import View

from apps.analysis_app.forms import PuSelectionForm, UploadDocxForm
from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun, CachedPU
from apps.analysis_app.pu_detection import detect_pu_from_docx
from apps.analysis_app.services import (
    _find_case_insensitive_span,
    _find_datetime_span,
    extract_attributes,
    highlight_text,
    match_event,
    parse_docx,
)
from apps.analysis_app.subdivision_matcher import (
    SUBDIVISION_GREEN_THRESHOLD,
    SUBDIVISION_YELLOW_THRESHOLD,
)
from apps.analysis_app.utils.dt_display import format_local_naive
from apps.analysis_app.utils.json_safe import offender_to_json
from apps.analysis_app.utils.offender_format import offender_display


def _format_offenders(offenders: list[dict], *, source: str) -> list[str]:
    return [offender_display(offender, source=source) for offender in offenders or []]


def _dedupe_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _status_for_timestamp(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    delta = match_result.get("time_delta_minutes")
    if delta is None:
        return "red"
    return "green" if delta <= 30 else "yellow"


def _status_for_subdivision(match_result: dict) -> str:
    score = match_result.get("subdivision_match_percent")
    if score is None:
        return "red"
    if match_result.get("subdivision_locality_mismatch") or match_result.get(
        "subdivision_unit_type_conflict"
    ):
        return "yellow" if score >= SUBDIVISION_YELLOW_THRESHOLD * 100 else "red"
    if score >= SUBDIVISION_GREEN_THRESHOLD * 100:
        return "green"
    if score >= SUBDIVISION_YELLOW_THRESHOLD * 100:
        return "yellow"
    return "red"


def _status_for_offenders(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    counts = match_result.get("offenders_counts") or {}
    matched = counts.get("matched", 0)
    portal_total = counts.get("portal_total", 0)
    has_issues = any(
        (
            counts.get("dob_mismatch", 0),
            counts.get("missing_in_portal", 0),
            counts.get("missing_in_svodka", 0),
        )
    )
    if matched == portal_total and not has_issues:
        return "green"
    if matched == 0 and (portal_total > 0 or has_issues):
        return "red"
    return "yellow"


def _build_offender_report(match_result: dict) -> dict:
    counts = match_result.get("offenders_counts") or {}
    summary = None
    if counts:
        summary = (
            "Совпало нарушителей: "
            f"{counts.get('matched', 0)} из {counts.get('portal_total', 0)}"
        )

    details = []
    matches = match_result.get("offender_matches") or {}

    dob_mismatch_pairs = matches.get("dob_mismatch_pairs") or []
    for pair in dob_mismatch_pairs:
        svodka_display = _format_offenders([pair.get("svodka_offender")], source="svodka")[0]
        portal_display = _format_offenders([pair.get("portal_offender")], source="portal")[0]
        details.append(
            f"ФИО совпало, но ДР отличается: {svodka_display} / {portal_display}"
        )

    missing_in_portal = _format_offenders(
        matches.get("missing_in_portal") or [], source="svodka"
    )
    missing_in_portal = _dedupe_items(missing_in_portal)
    if missing_in_portal:
        details.append(
            "В сводке есть, в БД нет: " + ", ".join(missing_in_portal)
        )

    missing_in_svodka = _format_offenders(
        matches.get("missing_in_svodka") or [], source="portal"
    )
    missing_in_svodka = _dedupe_items(missing_in_svodka)
    if missing_in_svodka:
        details.append(
            "В БД есть, в сводке нет: " + ", ".join(missing_in_svodka)
        )

    return {"summary": summary, "details": details}


def _build_highlighted_html(text: str, extracted: dict, match_result: dict) -> str:
    spans: list[tuple[int, int, str]] = []
    date_span = _find_datetime_span(text)
    if date_span:
        spans.append((date_span[0], date_span[1], f"hl-{_status_for_timestamp(match_result)}"))

    subdivision_span = extracted.get("subdivision_span")
    if subdivision_span:
        spans.append(
            (
                subdivision_span[0],
                subdivision_span[1],
                f"hl-{_status_for_subdivision(match_result)}",
            )
        )
    else:
        subdivision = extracted.get("subdivision_name")
        subdivision_span = _find_case_insensitive_span(text, subdivision) if subdivision else None
        if subdivision_span:
            spans.append(
                (
                    subdivision_span[0],
                    subdivision_span[1],
                    f"hl-{_status_for_subdivision(match_result)}",
                )
            )

    offenders = extracted.get("offenders") or []
    offender_status = f"hl-{_status_for_offenders(match_result)}"
    for offender in offenders:
        full_name = offender.get("full_name")
        offender_span = offender.get("span")
        if offender_span and len(offender_span) == 2:
            offender_span = (int(offender_span[0]), int(offender_span[1]))
        else:
            offender_span = _find_case_insensitive_span(text, full_name) if full_name else None
        if offender_span:
            spans.append((offender_span[0], offender_span[1], offender_status))

    return highlight_text(text, spans)


def _format_locality_label(locality: dict | None) -> str:
    if not locality:
        return "—"
    name = locality.get("name")
    if not name:
        return "—"
    locality_type = locality.get("type")
    display_name = str(name).replace("-", " ").title()
    if locality_type:
        return f"{locality_type}. {display_name}"
    return display_name


def _locality_mismatch_comment(match_result: dict) -> str:
    query_locality = _format_locality_label(match_result.get("subdivision_locality_query"))
    candidate_locality = _format_locality_label(match_result.get("subdivision_locality_candidate"))
    return (
        "Населённый пункт не совпадает: "
        f"в тексте '({query_locality})', в БД '({candidate_locality})'."
    )


def _build_comments(match_result: dict) -> list[str]:
    comments = []
    if not match_result.get("matched"):
        message = match_result.get("diffs", {}).get("message") or "Событие не найдено."
        comments.append(message)
        if match_result.get("date_time_present") and not match_result.get("time_found"):
            comments.append("Не определилось время (использована только дата).")
        if match_result.get("subdivision_locality_mismatch"):
            comments.append(_locality_mismatch_comment(match_result))
        debug_meta = match_result.get("debug") or {}
        if debug_meta:
            top_overlaps = debug_meta.get("top_overlaps") or {}
            comments.append(
                "Отладка подбора: "
                f"A={debug_meta.get('candidates_A', 0)}, "
                f"C={debug_meta.get('candidates_C', 0)}, "
                f"B={debug_meta.get('candidates_B', 0)}; "
                f"overlap C={top_overlaps.get('stage_c', 0)}, "
                f"B={top_overlaps.get('stage_b', 0)}; "
                f"method={debug_meta.get('chosen_method') or '—'}."
            )
        return comments

    diffs = match_result.get("diffs", {})
    if not diffs:
        comments.append("Расхождений не обнаружено.")
    if "subdivision" in diffs:
        comments.append("Подразделение не совпадает с БД.")
    if match_result.get("subdivision_locality_mismatch"):
        comments.append(_locality_mismatch_comment(match_result))
    if "offenders" in diffs:
        comments.append("Нарушители отличаются от данных БД.")
    if "event_type" in diffs:
        comments.append("Тип события отличается от классификации.")
    if "article_of_law" in diffs:
        comments.append("Статья закона отличается от классификации.")
    offender_report = _build_offender_report(match_result)
    if offender_report.get("summary"):
        comments.append(f"{offender_report['summary']}.")
    if match_result.get("date_time_present") and not match_result.get("time_found"):
        comments.append("Не определилось время (использована только дата).")
    return comments


def _build_event_card(paragraph: AnalysisParagraph) -> dict:
    result = paragraph.result
    extracted = result.extracted_attributes or {}
    match_result = result.match_result or {}
    text = paragraph.text
    preview = text[:80] + ("…" if len(text) > 80 else "")
    portal = match_result.get("portal") or {}
    predicted = match_result.get("predicted") or {}
    extracted_dt = parse_datetime(extracted.get("date_time") or "")
    portal_dt = parse_datetime(portal.get("timestamp") or "")
    extracted_timestamp_display = match_result.get(
        "extracted_timestamp_display"
    ) or format_local_naive(extracted_dt)
    portal_timestamp_display = match_result.get("portal_timestamp_display") or format_local_naive(
        portal_dt
    )

    subdivision_candidates = extracted.get("subdivision_candidates") or []
    formatted_candidates = []
    for candidate in subdivision_candidates:
        formatted_candidates.append(
            {
                "portal_subdivision_id": candidate.get("portal_subdivision_id"),
                "name": candidate.get("name"),
                "score": round(candidate.get("score", 0) * 100, 2)
                if candidate.get("score") is not None
                else None,
                "score_percent": candidate.get("score_percent"),
                "flags": candidate.get("flags"),
                "query_locality": candidate.get("query_locality"),
                "candidate_locality": candidate.get("candidate_locality"),
                "locality_mismatch": candidate.get("locality_mismatch"),
            }
        )

    offender_report = _build_offender_report(match_result)

    return {
        "idx": paragraph.idx,
        "preview": preview,
        "full_text": text,
        "highlighted_html": _build_highlighted_html(text, extracted, match_result),
        "extracted_timestamp_display": extracted_timestamp_display,
        "portal_timestamp_display": portal_timestamp_display,
        "extracted": {
            "date_time": extracted_timestamp_display,
            "subdivision_name": extracted.get("subdivision_name"),
            "subdivision_candidates": formatted_candidates,
            "offenders": _format_offenders(extracted.get("offenders") or [], source="svodka"),
        },
        "match": {
            "matched": bool(match_result.get("matched")),
            "score_percent": match_result.get("score_percent"),
            "time_delta_minutes": match_result.get("time_delta_minutes"),
            "offenders_score_percent": match_result.get("offenders_score_percent"),
            "offenders_counts": match_result.get("offenders_counts") or {},
            "offenders_summary": offender_report.get("summary"),
            "offenders_details": offender_report.get("details"),
            "subdivision_match_percent": match_result.get("subdivision_match_percent"),
        },
        "portal": {
            "timestamp": portal_timestamp_display,
            "subdivision_name": portal.get("subdivision_name"),
            "offenders": _format_offenders(portal.get("offenders") or [], source="portal"),
            "event_type": portal.get("event_type"),
            "article_of_law": portal.get("article_of_law"),
        },
        "predicted": {
            "event_type": predicted.get("event_type"),
            "article_of_law": predicted.get("article_of_law"),
        },
        "status": {
            "timestamp": _status_for_timestamp(match_result),
            "subdivision": _status_for_subdivision(match_result),
            "offenders": _status_for_offenders(match_result),
        },
        "comments": _build_comments(match_result),
    }


class UploadView(View):
    template_name = "analysis_app/upload.html"

    def get(self, request):
        return render(request, self.template_name, {"upload_form": UploadDocxForm()})

    def post(self, request):
        if request.FILES.get("file"):
            upload_form = UploadDocxForm(request.POST, request.FILES)
            if not upload_form.is_valid():
                return render(request, self.template_name, {"upload_form": upload_form})

            run = AnalysisRun.objects.create(
                uploaded_by=request.user if request.user.is_authenticated else None,
                file=upload_form.cleaned_data["file"],
            )
            from docx import Document

            document = Document(run.file.path)
            detection = detect_pu_from_docx(document)
            initial_pu_id = str(detection.pu.portal_pu_id) if detection.pu else ""
            selection_form = PuSelectionForm(
                initial={"upload_id": run.run_id, "selected_pu_id": initial_pu_id}
            )
            return render(
                request,
                self.template_name,
                {
                    "upload_form": UploadDocxForm(),
                    "selection_form": selection_form,
                    "detection": detection,
                },
            )

        selection_form = PuSelectionForm(request.POST)
        if not selection_form.is_valid():
            return render(
                request,
                self.template_name,
                {"upload_form": UploadDocxForm(), "selection_form": selection_form},
            )

        run = get_object_or_404(AnalysisRun, run_id=selection_form.cleaned_data["upload_id"])
        selected_pu_id = selection_form.cleaned_data["selected_pu_id"] or None
        run.selected_pu_id = selected_pu_id
        run.save(update_fields=["selected_pu_id"])

        try:
            paragraphs = parse_docx(run.file.path)
            for idx, text in enumerate(paragraphs, start=1):
                paragraph = AnalysisParagraph.objects.create(run=run, idx=idx, text=text)
                attributes = extract_attributes(text, selected_pu_id=selected_pu_id)
                match_result = match_event(attributes, text)
                AnalysisResult.objects.create(
                    paragraph=paragraph,
                    extracted_attributes={
                        "date_time": format_local_naive(attributes.date_time),
                        "time_found": attributes.time_found,
                        "subdivision_id": attributes.subdivision_id,
                        "subdivision_name": attributes.subdivision_name,
                        "subdivision_candidates": attributes.subdivision_candidates,
                        "subdivision_span": attributes.subdivision_span,
                        "offenders": [
                            offender_to_json(offender) for offender in attributes.offenders
                        ],
                    },
                    match_result=match_result,
                )
            run.status = AnalysisRun.Status.COMPLETED
            run.save(update_fields=["status"])
        except Exception as exc:  # noqa: BLE001 - capture for status update
            run.status = AnalysisRun.Status.FAILED
            run.save(update_fields=["status"])
            messages.error(request, f"Ошибка анализа: {exc}")
            return redirect("analysis-upload")

        return redirect("analysis-detail", run_id=run.run_id)


class AnalysisDetailView(View):
    template_name = "analysis_app/detail.html"

    def get(self, request, run_id):
        run = get_object_or_404(AnalysisRun, run_id=run_id)
        paragraphs = run.paragraphs.select_related("result").order_by("idx")
        events = [_build_event_card(paragraph) for paragraph in paragraphs]
        selected_idx = request.GET.get("event")
        try:
            selected_idx = int(selected_idx)
        except (TypeError, ValueError):
            selected_idx = events[0]["idx"] if events else None
        selected_event = next(
            (event for event in events if event["idx"] == selected_idx),
            events[0] if events else None,
        )
        selected_pu = None
        if run.selected_pu_id:
            selected_pu = CachedPU.objects.filter(
                portal_pu_id=run.selected_pu_id
            ).first()
        pu_label = "Общая сводка"
        if selected_pu:
            label_parts = [part for part in [selected_pu.short_name, selected_pu.full_name] if part]
            pu_label = " — ".join(label_parts) if label_parts else pu_label
        return render(
            request,
            self.template_name,
            {
                "run": run,
                "paragraphs": paragraphs,
                "events": events,
                "selected_event": selected_event,
                "selected_pu_label": pu_label,
            },
        )
