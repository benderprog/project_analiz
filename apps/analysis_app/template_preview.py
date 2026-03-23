from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Any

from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.analysis_app.document_parsers import extract_document_text
from apps.analysis_app.svodka_templates import parse_template_marker_blocks


@dataclass(frozen=True)
class TemplateMarker:
    kind: str
    span: tuple[int, int]
    line: int


@dataclass(frozen=True)
class TemplateSegment:
    begin_span: tuple[int, int]
    end_span: tuple[int, int] | None
    begin_line: int
    end_line: int | None
    start_anchor_line: int | None = None
    end_anchor_line: int | None = None
    start_anchor_text: str | None = None
    end_anchor_text: str | None = None
    open_ended: bool = False


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
    if not text or not begin:
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

    blocks, block_warnings = parse_template_marker_blocks(text, begin_marker=begin, end_marker=end)
    segments: list[TemplateSegment] = []
    for block in blocks:
        begin_line = _line_for_offset(line_starts, block.begin_marker_span[0])
        end_line = _line_for_offset(line_starts, block.end_marker_span[0]) if block.end_marker_span else None
        segments.append(
            TemplateSegment(
                begin_span=block.begin_marker_span,
                end_span=block.end_marker_span,
                begin_line=begin_line,
                end_line=end_line,
                start_anchor_line=max(begin_line - 1, 1) if block.pre_anchor_text else None,
                end_anchor_line=(end_line + 1) if (end_line and block.post_anchor_text) else None,
                start_anchor_text=block.pre_anchor_text,
                end_anchor_text=block.post_anchor_text,
                open_ended=block.end_marker_span is None,
            )
        )

    unmatched_begin = sum(1 for w in block_warnings if "BEGIN without END" in w)
    unmatched_end = sum(1 for w in block_warnings if "END without BEGIN" in w)
    return TemplateAnchorDetection(
        has_markers=True,
        segments=segments,
        markers=markers,
        unmatched_begin=unmatched_begin,
        unmatched_end=unmatched_end,
    )


def render_template_preview_html(text: str, markers: list[TemplateMarker], segments: list[TemplateSegment]) -> str:
    if not text:
        return ""

    chunks: list[str] = []
    cursor = 0
    anchor_line_classes: dict[int, str] = {}
    for segment in segments:
        if segment.start_anchor_line:
            anchor_line_classes[segment.start_anchor_line] = "template-anchor-start"
        if segment.end_anchor_line:
            anchor_line_classes[segment.end_anchor_line] = "template-anchor-end"

    line_starts = _line_starts(text)

    for marker in sorted(markers, key=lambda item: item.span[0]):
        start, finish = marker.span
        if start < cursor:
            continue

        before = escape(text[cursor:start])
        chunks.append(before)
        marker_text = escape(text[start:finish])
        css_class = "template-marker-begin" if marker.kind == "BEGIN" else "template-marker-end"
        line = _line_for_offset(line_starts, start)
        extra_anchor_class = f" {anchor_line_classes.get(line, '')}" if line in anchor_line_classes else ""
        chunks.append(f'<mark class="{css_class}{extra_anchor_class}">{marker_text}</mark>')
        cursor = finish

    chunks.append(escape(text[cursor:]))
    html = "".join(chunks)

    for line_no, css in anchor_line_classes.items():
        pattern = re.compile(rf"(^|\n)([^\n]*)", flags=re.MULTILINE)
        current = 0
        replaced = []
        for match in pattern.finditer(html):
            current += 1
            line_prefix, line_text = match.group(1), match.group(2)
            if current == line_no:
                replaced.append(f"{line_prefix}<mark class=\"{css}\">{line_text}</mark>")
            else:
                replaced.append(match.group(0))
        if replaced:
            html = "".join(replaced)

    return mark_safe(html)


def extract_template_text(file_obj: Any) -> str:
    if not file_obj:
        return ""

    file_obj.seek(0)
    try:
        extracted = extract_document_text(file_obj, filename=getattr(file_obj, "name", None))
        file_obj.seek(0)
        return "\n".join(extracted.text_blocks or extracted.lines)
    except Exception:  # noqa: BLE001
        file_obj.seek(0)
        raw_content = file_obj.read()
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

    for segment in detection.segments:
        if not segment.start_anchor_text:
            warnings.append("Нет строки перед [BEGIN], якорь начала не задан.")

    return {
        "has_text": bool(text),
        "segments_count": len(detection.segments),
        "markers_count": len(detection.markers),
        "warnings": warnings,
        "html": render_template_preview_html(text, detection.markers, detection.segments),
        "detection": detection,
        "segments": [
            {
                "index": idx + 1,
                "start_anchor": (segment.start_anchor_text or "").strip(),
                "end_anchor": (segment.end_anchor_text or "").strip(),
                "open_ended": segment.open_ended,
            }
            for idx, segment in enumerate(detection.segments)
        ],
    }
