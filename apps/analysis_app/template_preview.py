from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Any

from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.analysis_app.svodka_templates import iter_doc_elements


@dataclass(frozen=True)
class TemplateMarker:
    kind: str
    span: tuple[int, int]
    line: int


@dataclass(frozen=True)
class TemplateSegment:
    begin_span: tuple[int, int]
    end_span: tuple[int, int]
    begin_line: int
    end_line: int


@dataclass(frozen=True)
class TemplateAnchorDetection:
    has_markers: bool
    segments: list[TemplateSegment]
    markers: list[TemplateMarker]
    unmatched_begin: int = 0
    unmatched_end: int = 0


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for idx, char in enumerate(text):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def _line_for_offset(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def detect_template_anchors(text: str, begin: str = "[BEGIN]", end: str = "[END]") -> TemplateAnchorDetection:
    if not text or not begin or not end:
        return TemplateAnchorDetection(has_markers=False, segments=[], markers=[])

    line_starts = _line_starts(text)

    raw_markers: list[tuple[int, int, str]] = []
    for match in re.finditer(re.escape(begin), text, flags=re.IGNORECASE):
        raw_markers.append((match.start(), match.end(), "BEGIN"))
    for match in re.finditer(re.escape(end), text, flags=re.IGNORECASE):
        raw_markers.append((match.start(), match.end(), "END"))

    if not raw_markers:
        return TemplateAnchorDetection(has_markers=False, segments=[], markers=[])

    raw_markers.sort(key=lambda item: (item[0], 0 if item[2] == "BEGIN" else 1))

    markers = [
        TemplateMarker(kind=kind, span=(start, finish), line=_line_for_offset(line_starts, start))
        for start, finish, kind in raw_markers
    ]

    segments: list[TemplateSegment] = []
    active_begin: TemplateMarker | None = None
    unmatched_end = 0

    for marker in markers:
        if marker.kind == "BEGIN":
            if active_begin is None:
                active_begin = marker
            continue

        if active_begin is None:
            unmatched_end += 1
            continue

        segments.append(
            TemplateSegment(
                begin_span=active_begin.span,
                end_span=marker.span,
                begin_line=active_begin.line,
                end_line=marker.line,
            )
        )
        active_begin = None

    unmatched_begin = 1 if active_begin is not None else 0
    return TemplateAnchorDetection(
        has_markers=True,
        segments=segments,
        markers=markers,
        unmatched_begin=unmatched_begin,
        unmatched_end=unmatched_end,
    )


def render_template_preview_html(text: str, markers: list[TemplateMarker]) -> str:
    if not text:
        return ""

    chunks: list[str] = []
    cursor = 0

    for marker in sorted(markers, key=lambda item: item.span[0]):
        start, finish = marker.span
        if start < cursor:
            continue

        chunks.append(escape(text[cursor:start]))
        marker_text = escape(text[start:finish])
        css_class = "template-marker-begin" if marker.kind == "BEGIN" else "template-marker-end"
        chunks.append(f'<mark class="{css_class}">{marker_text}</mark>')
        cursor = finish

    chunks.append(escape(text[cursor:]))
    return mark_safe("".join(chunks))


def extract_template_text(file_obj: Any) -> str:
    if not file_obj:
        return ""

    file_obj.seek(0)
    raw_content = file_obj.read()
    file_obj.seek(0)

    try:
        from docx import Document

        document = Document(file_obj)
        lines = [element.text for element in iter_doc_elements(document) if element.text]
        file_obj.seek(0)
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        file_obj.seek(0)
        if isinstance(raw_content, bytes):
            return raw_content.decode("utf-8", errors="ignore")
        return str(raw_content or "")


def build_template_preview_context(text: str, begin_marker: str, end_marker: str) -> dict[str, Any]:
    detection = detect_template_anchors(text, begin_marker, end_marker)
    warnings: list[str] = []

    if not detection.has_markers:
        warnings.append("Маркеры не обнаружены — будет анализироваться вся сводка.")
    if detection.unmatched_begin:
        warnings.append("Обнаружен BEGIN без завершающего END.")
    if detection.unmatched_end:
        warnings.append("Обнаружен END без открывающего BEGIN.")

    return {
        "has_text": bool(text),
        "segments_count": len(detection.segments),
        "markers_count": len(detection.markers),
        "warnings": warnings,
        "html": render_template_preview_html(text, detection.markers),
        "detection": detection,
    }
