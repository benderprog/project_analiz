from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.analysis_app.forms import UploadDocxForm
from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun
from apps.analysis_app.services import (
    _find_case_insensitive_span,
    _find_datetime_span,
    extract_attributes,
    highlight_text,
    match_event,
    parse_docx,
)


def _format_offenders(offenders: list[dict]) -> list[str]:
    formatted = []
    for offender in offenders or []:
        name = offender.get("full_name") or "—"
        birth_year = offender.get("birth_year")
        if birth_year:
            formatted.append(f"{name} ({birth_year})")
        else:
            formatted.append(name)
    return formatted


def _status_for_timestamp(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    delta = match_result.get("time_delta_minutes")
    if delta is None:
        return "red"
    return "green" if delta <= 30 else "yellow"


def _status_for_subdivision(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    diffs = match_result.get("diffs", {})
    return "yellow" if "subdivision" in diffs else "green"


def _status_for_offenders(match_result: dict) -> str:
    if not match_result.get("matched"):
        return "red"
    offenders_score = match_result.get("offenders_score_percent") or 0
    diffs = match_result.get("diffs", {})
    if "offenders" not in diffs:
        return "green"
    return "yellow" if offenders_score > 0 else "red"


def _build_highlighted_html(text: str, extracted: dict, match_result: dict) -> str:
    spans: list[tuple[int, int, str]] = []
    date_span = _find_datetime_span(text)
    if date_span:
        spans.append((date_span[0], date_span[1], f"hl-{_status_for_timestamp(match_result)}"))

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
        offender_span = _find_case_insensitive_span(text, full_name) if full_name else None
        if offender_span:
            spans.append((offender_span[0], offender_span[1], offender_status))

    return highlight_text(text, spans)


def _build_comments(match_result: dict) -> list[str]:
    comments = []
    if not match_result.get("matched"):
        message = match_result.get("diffs", {}).get("message") or "Событие не найдено."
        comments.append(message)
        if match_result.get("date_time_present") and not match_result.get("time_found"):
            comments.append("Не определилось время (использована только дата).")
        return comments

    diffs = match_result.get("diffs", {})
    if not diffs:
        comments.append("Расхождений не обнаружено.")
    if "subdivision" in diffs:
        comments.append("Подразделение не совпадает с БД.")
    if "offenders" in diffs:
        comments.append("Нарушители отличаются от данных БД.")
    if "event_type" in diffs:
        comments.append("Тип события отличается от классификации.")
    if "article_of_law" in diffs:
        comments.append("Статья закона отличается от классификации.")
    offenders_counts = match_result.get("offenders_counts", {})
    if offenders_counts:
        comments.append(
            "Совпало нарушителей: "
            f"{offenders_counts.get('matched', 0)} из {offenders_counts.get('portal', 0)}."
        )
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

    return {
        "idx": paragraph.idx,
        "preview": preview,
        "full_text": text,
        "highlighted_html": _build_highlighted_html(text, extracted, match_result),
        "extracted": {
            "date_time": extracted.get("date_time"),
            "subdivision_name": extracted.get("subdivision_name"),
            "offenders": _format_offenders(extracted.get("offenders") or []),
        },
        "match": {
            "matched": bool(match_result.get("matched")),
            "score_percent": match_result.get("score_percent"),
            "time_delta_minutes": match_result.get("time_delta_minutes"),
            "offenders_score_percent": match_result.get("offenders_score_percent"),
            "offenders_counts": match_result.get("offenders_counts") or {},
            "subdivision_match_percent": match_result.get("subdivision_match_percent"),
        },
        "portal": {
            "timestamp": portal.get("timestamp"),
            "subdivision_name": portal.get("subdivision_name"),
            "offenders": _format_offenders(portal.get("offenders") or []),
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
        return render(request, self.template_name, {"form": UploadDocxForm()})

    def post(self, request):
        form = UploadDocxForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        run = AnalysisRun.objects.create(
            uploaded_by=request.user if request.user.is_authenticated else None,
            file=form.cleaned_data["file"],
        )
        try:
            paragraphs = parse_docx(run.file.path)
            for idx, text in enumerate(paragraphs, start=1):
                paragraph = AnalysisParagraph.objects.create(run=run, idx=idx, text=text)
                attributes = extract_attributes(text)
                match_result = match_event(attributes, text)
                AnalysisResult.objects.create(
                    paragraph=paragraph,
                    extracted_attributes={
                        "date_time": attributes.date_time.isoformat()
                        if attributes.date_time
                        else None,
                        "time_found": attributes.time_found,
                        "subdivision_id": attributes.subdivision_id,
                        "subdivision_name": attributes.subdivision_name,
                        "offenders": attributes.offenders,
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
        return render(
            request,
            self.template_name,
            {
                "run": run,
                "paragraphs": paragraphs,
                "events": events,
                "selected_event": selected_event,
            },
        )
