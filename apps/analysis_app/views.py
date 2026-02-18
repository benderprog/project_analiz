import logging
import os
from pathlib import PurePath
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
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
)
from apps.analysis_app.subdivision_matcher import (
    SUBDIVISION_GREEN_THRESHOLD,
    SUBDIVISION_YELLOW_THRESHOLD,
)
from apps.analysis_app.utils.dt_display import format_dt_dmy_hm
from apps.analysis_app.utils.offender_format import offender_display

TIME_ERROR_MINUTES = int(getattr(settings, "TIME_ERROR_MINUTES", 30))


logger = logging.getLogger(__name__)


def _display_filename(file_name: str | None) -> str:
    if not file_name:
        return ""
    normalized = str(file_name).replace("\\", "/")
    return PurePath(normalized).name


def _format_offenders(offenders: list[dict], *, source: str) -> list[str]:
    return [offender_display(offender, source=source) for offender in offenders or []]


def _status_key_for_offender(offender: dict | None) -> str:
    offender = offender or {}
    span = offender.get("span")
    if isinstance(span, list) and len(span) == 2:
        return f"{int(span[0])}:{int(span[1])}"
    if isinstance(span, tuple) and len(span) == 2:
        return f"{int(span[0])}:{int(span[1])}"
    full_name = " ".join(str(offender.get("full_name") or "").lower().split())
    birth_year = offender.get("birth_year")
    birth_date = offender.get("birth_date")
    if not birth_year and isinstance(birth_date, str) and len(birth_date) >= 4:
        birth_year = birth_date[:4]
    elif not birth_year and hasattr(birth_date, "year"):
        birth_year = birth_date.year
    return f"fio:{full_name}|year:{birth_year or ''}"


def _format_offenders_with_status(offenders: list[dict], *, match_result: dict, source: str) -> list[dict]:
    status_map = (match_result.get("offender_matches") or {}).get("svodka_status_by_span") or {}
    formatted = []
    status_to_css = {
        "ok": "hl-green",
        "warn": "hl-yellow",
        "err": "hl-red",
    }
    for offender in offenders or []:
        key = _status_key_for_offender(offender)
        status = status_map.get(key, "warn")
        formatted.append(
            {
                "text": offender_display(offender, source=source),
                "status": status,
                "status_css": status_to_css.get(status, "hl-yellow"),
            }
        )
    return formatted


def _dedupe_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _offender_dedupe_key(offender: dict | None) -> tuple[str, str]:
    offender = offender or {}
    full_name = str(offender.get("full_name") or "").strip().lower()
    birth_date = str(offender.get("birth_date") or offender.get("birth_year") or "")
    return full_name, birth_date


def _dedupe_pairs(pairs: list[dict], *, key_getter) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for pair in pairs:
        key = key_getter(pair)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pair)
    return deduped


def _status_for_timestamp(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    delta = match_result.get("time_delta_minutes")
    if delta is None:
        return "red"
    delta_abs = abs(delta)
    if delta_abs == 0:
        return "green"
    if delta_abs <= TIME_ERROR_MINUTES:
        return "yellow"
    return "red"


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

    matched_pairs = _dedupe_pairs(
        matches.get("matched_pairs") or [],
        key_getter=lambda pair: (
            _offender_dedupe_key(pair.get("svodka_offender")),
            _offender_dedupe_key(pair.get("portal_offender")),
            pair.get("match_type"),
            pair.get("discrepancy"),
        ),
    )
    for pair in matched_pairs:
        discrepancy = pair.get("discrepancy")
        if not discrepancy:
            continue
        svodka_display = _format_offenders([pair.get("svodka_offender")], source="svodka")[0]
        portal_display = _format_offenders([pair.get("portal_offender")], source="portal")[0]
        details.append(
            f"ФИО совпало частично/с ошибкой: {svodka_display} / {portal_display} ({discrepancy})"
        )

    dob_mismatch_pairs = _dedupe_pairs(
        matches.get("dob_mismatch_pairs") or [],
        key_getter=lambda pair: (
            _offender_dedupe_key(pair.get("svodka_offender")),
            _offender_dedupe_key(pair.get("portal_offender")),
            pair.get("reason"),
        ),
    )
    for pair in dob_mismatch_pairs:
        svodka_display = _format_offenders([pair.get("svodka_offender")], source="svodka")[0]
        portal_display = _format_offenders([pair.get("portal_offender")], source="portal")[0]
        details.append(
            f"Возможное совпадение по ФИО, но ДР отличается: {svodka_display} / {portal_display}"
        )

    ambiguous = matches.get("ambiguous") or []
    for item in ambiguous:
        svodka_display = _format_offenders([item.get("svodka_offender")], source="svodka")[0]
        details.append(f"Неоднозначное совпадение: {svodka_display}")

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
    strong_spans: list[tuple[int, int]] = []

    def _add_span(start: int, end: int, css_class: str, *, is_strong: bool = True) -> None:
        if end <= start:
            return
        spans.append((start, end, css_class))
        if is_strong:
            strong_spans.append((start, end))

    timestamp_css = f"hl-{_status_for_timestamp(match_result)}"
    date_span = extracted.get("date_span")
    time_span = extracted.get("time_span")
    if isinstance(date_span, (list, tuple)) and len(date_span) == 2:
        _add_span(int(date_span[0]), int(date_span[1]), timestamp_css)
    else:
        fallback_date_span = _find_datetime_span(text)
        if fallback_date_span:
            _add_span(int(fallback_date_span[0]), int(fallback_date_span[1]), timestamp_css)
    if isinstance(time_span, (list, tuple)) and len(time_span) == 2:
        time_span_tuple = (int(time_span[0]), int(time_span[1]))
        _add_span(time_span_tuple[0], time_span_tuple[1], timestamp_css)
        logger.debug("time highlight applied span=%s", time_span_tuple)
    else:
        logger.debug("time highlight skipped (no time span)")


    subdivision_span = extracted.get("subdivision_span")
    if subdivision_span:
        _add_span(
            subdivision_span[0],
            subdivision_span[1],
            f"hl-{_status_for_subdivision(match_result)}",
        )
    else:
        subdivision = extracted.get("subdivision_name")
        subdivision_span = _find_case_insensitive_span(text, subdivision) if subdivision else None
        if subdivision_span:
            _add_span(
                subdivision_span[0],
                subdivision_span[1],
                f"hl-{_status_for_subdivision(match_result)}",
            )

    safe_match_result = match_result or {}
    article_status = safe_match_result.get("article_status") or _status_from_flag(safe_match_result.get("article_ok"))
    article_css = {
        "green": "hl-green",
        "yellow": "hl-yellow",
        "red": "hl-red",
    }.get(article_status)
    article_spans = extracted.get("article_spans") or []
    if article_css:
        for span in article_spans:
            if isinstance(span, (list, tuple)) and len(span) == 2:
                _add_span(int(span[0]), int(span[1]), article_css)

    offenders = extracted.get("offenders") or []
    status_map = (match_result.get("offender_matches") or {}).get("svodka_status_by_span") or {}
    status_to_css = {
        "ok": "hl-green",
        "warn": "hl-yellow",
        "err": "hl-red",
    }
    offender_spans: list[tuple[int, int]] = []
    for offender in offenders:
        offender_status = status_to_css.get(status_map.get(_status_key_for_offender(offender), "warn"), "hl-yellow")
        full_name = offender.get("full_name")
        offender_span = offender.get("span")
        if offender_span and len(offender_span) == 2:
            offender_span = (int(offender_span[0]), int(offender_span[1]))
        else:
            offender_span = _find_case_insensitive_span(text, full_name) if full_name else None
        if offender_span:
            offender_spans.append(offender_span)
            _add_span(offender_span[0], offender_span[1], offender_status)
        dob_span = offender.get("dob_span")
        if dob_span and len(dob_span) == 2:
            _add_span(int(dob_span[0]), int(dob_span[1]), offender_status)

    for staff_item in extracted.get("staff") or []:
        staff_span = staff_item.get("span") if isinstance(staff_item, dict) else None
        if not (staff_span and len(staff_span) == 2):
            continue
        staff_span = (int(staff_span[0]), int(staff_span[1]))
        overlaps_offender = any(
            min(staff_span[1], offender_span[1]) - max(staff_span[0], offender_span[0]) > 0
            for offender_span in offender_spans
        )
        if overlaps_offender:
            continue
        _add_span(staff_span[0], staff_span[1], "hl-green hl-staff")

    predicted = (match_result or {}).get("predicted")
    if not isinstance(predicted, dict):
        predicted = {}
    event_match = predicted.get("event_type_match") or predicted.get("event_pattern")
    if not isinstance(event_match, dict):
        event_match = {}
    span = event_match.get("span")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        event_span = (int(span[0]), int(span[1]))
        overlaps_strong = any(
            min(event_span[1], strong_span[1]) - max(event_span[0], strong_span[0]) > 0
            for strong_span in strong_spans
        )
        if not overlaps_strong:
            _add_span(event_span[0], event_span[1], "hl-green hl-eventpattern", is_strong=False)

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
    extracted_subdivision_name = match_result.get("extracted_subdivision_name")
    if not match_result.get("matched"):
        message = match_result.get("diffs", {}).get("message") or "Событие не найдено."
        comments.append(message)
        if match_result.get("date_time_present") and not match_result.get("time_found"):
            comments.append("Не определилось время (использована только дата).")
        if extracted_subdivision_name is None:
            comments.append("Подразделение не определено в сводке.")
        if match_result.get("subdivision_locality_mismatch"):
            comments.append(_locality_mismatch_comment(match_result))
        debug_meta = match_result.get("debug") or {}
        if debug_meta:
            stage_counts = ", ".join(
                f"{item.get('stage')}={item.get('count', 0)}"
                for item in (debug_meta.get("candidate_stages") or [])
            ) or "—"
            comments.append(
                "Отладка подбора: "
                f"candidates={debug_meta.get('candidates_total', 0)}; "
                "subdivision candidates "
                f"total={debug_meta.get('subdivision_candidates_total', 0)}, "
                f"after PU={debug_meta.get('subdivision_candidates_after_pu_filter', 0)}, "
                f"fallback={debug_meta.get('pu_filter_fallback_used', False)}, "
                f"pu={debug_meta.get('selected_pu_id') or '—'}; "
                f"stage1 score={debug_meta.get('stage1_best_score', 0)}/"
                f"{debug_meta.get('score_threshold', 2)}, "
                f"high_conf={debug_meta.get('subdivision_confidence_high', False)}, "
                f"stages: {stage_counts}; "
                f"method={debug_meta.get('chosen_method') or '—'}."
            )
        return comments

    diffs = match_result.get("diffs", {})
    if not diffs:
        comments.append("Расхождений не обнаружено.")
    if "subdivision" in diffs and extracted_subdivision_name:
        comments.append("Подразделение не совпадает с БД.")
    elif extracted_subdivision_name is None:
        comments.append("Подразделение не определено в сводке.")
    if match_result.get("subdivision_locality_mismatch"):
        comments.append(_locality_mismatch_comment(match_result))
    if "offenders" in diffs:
        comments.append("Нарушители отличаются от данных БД.")
    if match_result.get("event_type_ok") is False:
        comments.append("Тип события отличается от классификации.")
    article_status = match_result.get("article_status")
    article_ok = match_result.get("article_ok")
    article_classifier_ok = match_result.get("article_classifier_ok")
    if article_ok is False:
        comments.append("Статья закона отличается от данных БД.")
    elif article_ok is True and article_classifier_ok is False:
        comments.append("Статья закона отличается от классификации.")

    classifier_article_raw = (
        match_result.get("classifier_article_of_law")
        or (match_result.get("predicted") or {}).get("classifier_article_of_law")
    )
    if article_classifier_ok is False:
        classifier_article = _display_article(classifier_article_raw)
        if classifier_article:
            comments.append(f"По классификатору ожидается: {classifier_article}.")
    if match_result.get("svodka_article_of_law") is None and article_status in {"red", "yellow"}:
        comments.append("Статья закона не определена в тексте сводки.")
    if match_result.get("time_mismatch"):
        date_diff = (diffs.get("date_time") or {})
        if date_diff.get("message"):
            comments.append(date_diff["message"])
        if date_diff.get("delta_minutes") is not None:
            comments.append(
                f"Δ времени: {date_diff['delta_minutes']} мин. "
                f"Извлечено: {date_diff.get('extracted') or '—'}, "
                f"портал: {date_diff.get('portal') or '—'}."
            )
    delta_minutes = match_result.get("time_delta_minutes")
    if delta_minutes is not None and abs(delta_minutes) > TIME_ERROR_MINUTES:
        comments.append(
            "Ошибка: расхождение даты/времени на "
            f"{delta_minutes} мин (более {TIME_ERROR_MINUTES} мин)."
        )
    offender_report = _build_offender_report(match_result)
    if offender_report.get("summary"):
        comments.append(f"{offender_report['summary']}.")
    if match_result.get("date_time_present") and not match_result.get("time_found"):
        comments.append("Не определилось время (использована только дата).")
    return comments


def _status_from_flag(flag: bool | None) -> str:
    if flag is True:
        return "green"
    if flag is False:
        return "red"
    return "neutral"


def _display_article(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null" or text in {"-", "—"}:
        return None
    return text


def _build_event_card(paragraph: AnalysisParagraph) -> dict:
    result = paragraph.result
    extracted = result.extracted_attributes or {}
    match_result = result.match_result or {}
    text = paragraph.text

    needs_backfill = (
        not match_result
        or "event_type_ok" not in match_result
        or "article_ok" not in match_result
        or "article_classifier_ok" not in match_result
        or "article_status" not in match_result
        or "article_spans" not in extracted
        or "date_span" not in extracted
        or "time_span" not in extracted
        or (
            match_result.get("matched") is True
            and (
                not isinstance(match_result.get("predicted"), dict)
                or match_result.get("predicted", {}).get("event_type") is None
                or match_result.get("predicted", {}).get("classifier_article_of_law") is None
            )
        )
    )
    if needs_backfill:
        try:
            paragraph_run = getattr(paragraph, "run", None)
            selected_pu_id = getattr(paragraph_run, "selected_pu_id", None)
            extracted_attrs = extract_attributes(text, selected_pu_id=selected_pu_id)
            new_match_result = match_event(extracted_attrs, text)
            extracted = {
                "date_time": format_local_naive(extracted_attrs.date_time),
                "time_found": extracted_attrs.time_found,
                "date_span": list(extracted_attrs.date_span) if extracted_attrs.date_span else None,
                "time_span": list(extracted_attrs.time_span) if extracted_attrs.time_span else None,
                "subdivision_id": extracted_attrs.subdivision_id,
                "subdivision_name": extracted_attrs.subdivision_name,
                "subdivision_candidates": extracted_attrs.subdivision_candidates,
                "subdivision_span": extracted_attrs.subdivision_span,
                "article_spans": [list(span) for span in extracted_attrs.article_spans],
                "offenders": [offender_to_json(offender) for offender in extracted_attrs.offenders],
                "staff": extracted_attrs.staff,
            }
            match_result = new_match_result
            result.extracted_attributes = extracted
            result.match_result = new_match_result
            result.save(update_fields=["extracted_attributes", "match_result"])
        except Exception:  # noqa: BLE001 - page should remain renderable
            match_result = result.match_result or match_result
    preview = text[:80] + ("…" if len(text) > 80 else "")
    portal = match_result.get("portal") or {}
    predicted = match_result.get("predicted") or {}
    classifier_article = (
        match_result.get("classifier_article_of_law")
        or predicted.get("classifier_article_of_law")
    )
    extracted_dt = parse_datetime(extracted.get("date_time") or "")
    portal_dt = parse_datetime(portal.get("timestamp") or "")
    extracted_timestamp_display = match_result.get(
        "extracted_timestamp_display"
    ) or format_dt_dmy_hm(extracted_dt)
    portal_timestamp_display = match_result.get("portal_timestamp_display") or format_dt_dmy_hm(
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
                "semantic_score": round(candidate.get("semantic_score", 0) * 100, 2)
                if candidate.get("semantic_score") is not None
                else None,
                "lexical_factor": candidate.get("lexical_factor"),
                "flags": candidate.get("flags"),
                "query_locality": candidate.get("query_locality"),
                "candidate_locality": candidate.get("candidate_locality"),
                "locality_mismatch": candidate.get("locality_mismatch"),
            }
        )

    offender_report = _build_offender_report(match_result)
    not_found = not bool(match_result.get("matched"))
    title = f"Событие {paragraph.idx}" + (" — в базе данных не найдено" if not_found else "")

    return {
        "idx": paragraph.idx,
        "title": title,
        "not_found": not_found,
        "preview": preview,
        "full_text": text,
        "highlighted_html": _build_highlighted_html(text, extracted, match_result),
        "extracted_timestamp_display": extracted_timestamp_display,
        "portal_timestamp_display": portal_timestamp_display,
        "extracted": {
            "date_time": extracted_timestamp_display,
            "subdivision_name": extracted.get("subdivision_name"),
            "subdivision_candidates": formatted_candidates,
            "offenders": _format_offenders_with_status(
                extracted.get("offenders") or [],
                match_result=match_result,
                source="svodka",
            ),
            "staff": [item.get("display") for item in (extracted.get("staff") or []) if item.get("display")],
        },
        "match": {
            "matched": bool(match_result.get("matched")),
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
            "article_of_law": _display_article(portal.get("article_of_law")),
        },
        "predicted": {
            "event_type": predicted.get("event_type"),
            "article_of_law": _display_article(predicted.get("article_of_law")),
            "classifier_article_of_law": _display_article(classifier_article),
        },
        "status": {
            "timestamp": _status_for_timestamp(match_result),
            "subdivision": _status_for_subdivision(match_result),
            "offenders": _status_for_offenders(match_result),
            "event_type": _status_from_flag(match_result.get("event_type_ok")),
            "article": (match_result.get("article_status") or _status_from_flag(match_result.get("article_ok"))),
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
                original_filename=os.path.basename(upload_form.cleaned_data["file"].name or ""),
                status=AnalysisRun.Status.CREATED,
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
        selected_pu_id = selection_form.cleaned_data["selected_pu_id"]
        run.selected_pu_id = selected_pu_id
        run.status = AnalysisRun.Status.QUEUED
        run.queued_at = timezone.now()
        run.error_message = ""
        run.save(update_fields=["selected_pu_id", "status", "queued_at", "error_message"])

        if getattr(settings, "ANALYSIS_USE_SYNC_TASKS", False):
            from apps.analysis_app.services import run_analysis_pipeline
            from apps.analysis_app.tasks import cleanup_run_upload

            run.status = AnalysisRun.Status.RUNNING
            run.started_at = timezone.now()
            run.save(update_fields=["status", "started_at"])
            try:
                run_analysis_pipeline(run, selected_pu_id=selected_pu_id)
                run.status = AnalysisRun.Status.DONE
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "finished_at"])
            except Exception as exc:  # noqa: BLE001
                run.status = AnalysisRun.Status.FAILED
                run.error_message = str(exc)
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error_message", "finished_at"])
            cleanup_run_upload(run)
            return render(
                request,
                self.template_name,
                {
                    "analysis_started": True,
                    "analysis_run_id": str(run.run_id),
                    "status_poll_url": redirect("analysis-status", run_id=run.run_id).url,
                    "result_url": redirect("analysis-detail", run_id=run.run_id).url,
                    "uploaded_filename": run.original_filename or _display_filename(run.file.name),
                },
            )

        from apps.analysis_app.tasks import run_docx_analysis

        task = run_docx_analysis.delay(str(run.run_id), str(selected_pu_id) if selected_pu_id else None)
        run.celery_task_id = task.id
        run.save(update_fields=["celery_task_id"])

        return render(
            request,
            self.template_name,
            {
                "analysis_started": True,
                "analysis_run_id": str(run.run_id),
                "status_poll_url": redirect("analysis-status", run_id=run.run_id).url,
                "result_url": redirect("analysis-detail", run_id=run.run_id).url,
                "uploaded_filename": run.original_filename or _display_filename(run.file.name),
            },
        )


class AnalysisStatusView(View):
    def get(self, request, run_id):
        run = get_object_or_404(AnalysisRun, run_id=run_id)

        now = timezone.now()
        elapsed_base = run.started_at or run.queued_at or run.created_at
        elapsed_end = run.finished_at or now
        elapsed_seconds = int((elapsed_end - elapsed_base).total_seconds()) if elapsed_base else 0

        if getattr(settings, "ANALYSIS_USE_SYNC_TASKS", False):
            worker_ok = True
        else:
            from config.celery import app as celery_app

            worker_response = celery_app.control.inspect(timeout=1).ping() or {}
            worker_ok = bool(worker_response)

        payload = {
            "status": run.status,
            "queued_at": run.queued_at.isoformat() if run.queued_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "elapsed_seconds": max(elapsed_seconds, 0),
            "error_message": run.error_message if run.status == AnalysisRun.Status.FAILED else None,
            "worker_ok": worker_ok,
            "uploaded_filename": run.original_filename or _display_filename(run.file.name),
        }
        if run.status == AnalysisRun.Status.DONE:
            payload["result_url"] = redirect("analysis-detail", run_id=run.run_id).url
        return JsonResponse(payload)


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
