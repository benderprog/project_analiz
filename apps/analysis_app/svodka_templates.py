from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from django.db.models import QuerySet

from apps.analysis_app.models import SvodkaTemplate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocElement:
    kind: str
    text: str
    cells: list[str] | None = None
    table_header_cells: list[str] | None = None
    is_table_header: bool = False


@dataclass(frozen=True)
class SegmentAnchors:
    start_anchor_text: str
    end_anchor_text: str


@dataclass(frozen=True)
class SlicingDebugInfo:
    selected_template: SvodkaTemplate | None
    template_segments_total: int
    segments_applied: int
    segments_failed: int
    kept_elements: int
    total_elements: int
    fallback_reason: str | None = None


_TABLE_HEADER_KEYWORDS = (
    "дата",
    "время",
    "подраздел",
    "пу",
    "кпп",
    "событ",
    "наруш",
    "статья",
    "комментар",
)


def _normalize_ws(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _looks_like_table_header(rows: list[list[str]], min_chars: int) -> bool:
    if not rows:
        return False
    header_cells = rows[0]
    if not any(header_cells):
        return False

    lowered = [cell.lower() for cell in header_cells if cell]
    if any(keyword in cell for cell in lowered for keyword in _TABLE_HEADER_KEYWORDS):
        return True

    if len(rows) < 2:
        return False

    header_is_short = all(len(cell) <= 40 for cell in header_cells if cell)
    if not header_is_short:
        return False

    row_1_joined = _normalize_ws(" ".join(rows[1]))
    return len(row_1_joined) >= min_chars


def iter_doc_elements(document, min_chars: int = 100) -> list[DocElement]:
    from docx.document import Document as DocxDocument
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if not isinstance(document, DocxDocument):
        raise TypeError("document must be an instance of docx.document.Document")

    elements: list[DocElement] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            elements.append(DocElement(kind="paragraph", text=_normalize_ws(getattr(paragraph, "text", ""))))
            continue

        if not isinstance(child, CT_Tbl):
            continue

        table = Table(child, document)
        rows = [[_normalize_ws(cell.text) for cell in row.cells] for row in table.rows]
        if not rows:
            continue

        header_cells: list[str] | None = rows[0] if _looks_like_table_header(rows, min_chars) else None
        for row_index, cells in enumerate(rows):
            is_header = bool(header_cells is not None and row_index == 0)
            elements.append(
                DocElement(
                    kind="table_row",
                    text=" | ".join(cells),
                    cells=cells,
                    table_header_cells=None if is_header else header_cells,
                    is_table_header=is_header,
                )
            )

    return elements


def _strip_markers(text: str, begin_marker: str, end_marker: str) -> str:
    cleaned = text
    if begin_marker:
        cleaned = re.sub(re.escape(begin_marker), " ", cleaned, flags=re.IGNORECASE)
    if end_marker:
        cleaned = re.sub(re.escape(end_marker), " ", cleaned, flags=re.IGNORECASE)
    return _normalize_ws(cleaned)


def _element_texts_for_segments(template_doc_or_elements: Any) -> list[str]:
    if isinstance(template_doc_or_elements, Sequence) and all(
        isinstance(item, DocElement) for item in template_doc_or_elements
    ):
        return [item.text for item in template_doc_or_elements]
    return [element.text for element in iter_doc_elements(template_doc_or_elements)]


def build_template_segments(template_doc, begin_marker: str, end_marker: str) -> list[SegmentAnchors]:
    texts = _element_texts_for_segments(template_doc)
    if not begin_marker or not end_marker:
        return []

    segments: list[SegmentAnchors] = []
    inside_segment = False
    current_segment_items: list[str] = []

    for text in texts:
        lowered = text.lower()
        has_begin = begin_marker.lower() in lowered
        has_end = end_marker.lower() in lowered

        if has_begin and not inside_segment:
            inside_segment = True
            current_segment_items = []

        if inside_segment:
            candidate = _strip_markers(text, begin_marker, end_marker)
            if candidate:
                current_segment_items.append(candidate)

        if has_end and inside_segment:
            if current_segment_items:
                segments.append(
                    SegmentAnchors(
                        start_anchor_text=current_segment_items[0],
                        end_anchor_text=current_segment_items[-1],
                    )
                )
            inside_segment = False
            current_segment_items = []

    return segments


def _normalize_anchor_text(text: str) -> str:
    normalized = (text or "").lower().replace("ё", "е")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"^[^\wа-яА-Я]+|[^\wа-яА-Я]+$", "", normalized)
    return normalized


def _anchors_match(anchor: str, element_text: str) -> bool:
    anchor_norm = _normalize_anchor_text(anchor)
    element_norm = _normalize_anchor_text(element_text)
    if not anchor_norm or not element_norm:
        return False
    return anchor_norm in element_norm or element_norm in anchor_norm


def apply_template_segments(
    target_elements: Sequence[DocElement],
    segment_anchors: Sequence[SegmentAnchors],
) -> tuple[list[DocElement], int, int]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    failed_segments = 0

    for segment in segment_anchors:
        start_idx = next(
            (
                idx
                for idx, element in enumerate(target_elements[cursor:], start=cursor)
                if _anchors_match(segment.start_anchor_text, element.text)
            ),
            None,
        )
        if start_idx is None:
            failed_segments += 1
            continue

        end_idx = next(
            (
                idx
                for idx in range(start_idx, len(target_elements))
                if _anchors_match(segment.end_anchor_text, target_elements[idx].text)
            ),
            None,
        )
        if end_idx is None:
            failed_segments += 1
            continue

        if end_idx < start_idx:
            failed_segments += 1
            continue

        ranges.append((start_idx, end_idx))
        cursor = end_idx + 1

    if not ranges:
        return [], 0, failed_segments

    ranges.sort(key=lambda pair: pair[0])
    merged: list[list[int]] = [[ranges[0][0], ranges[0][1]]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    sliced: list[DocElement] = []
    for start, end in merged:
        sliced.extend(target_elements[start : end + 1])
    return sliced, len(ranges), failed_segments


def _query_active_templates() -> QuerySet[SvodkaTemplate]:
    return SvodkaTemplate.objects.filter(is_active=True)


def get_template_for_run(selected_pu_id: str | None, selected_pu_name: str | None) -> SvodkaTemplate | None:
    selected_pu_id = (selected_pu_id or "").strip()
    selected_pu_name = (selected_pu_name or "").strip()

    if selected_pu_id:
        return (
            _query_active_templates()
            .filter(scope=SvodkaTemplate.Scope.PU, pu_id=selected_pu_id)
            .order_by("-updated_at")
            .first()
        )

    if selected_pu_name == "Общая сводка":
        return (
            _query_active_templates()
            .filter(scope=SvodkaTemplate.Scope.GENERAL, pu_id="")
            .order_by("-updated_at")
            .first()
        )

    return None


def slice_document_for_run(document, selected_pu_id: str | None, selected_pu_name: str | None, *, min_chars: int = 100) -> tuple[list[DocElement], SlicingDebugInfo]:
    target_elements = iter_doc_elements(document, min_chars=min_chars)
    template = get_template_for_run(selected_pu_id, selected_pu_name)

    if not template or not template.file:
        return target_elements, SlicingDebugInfo(
            selected_template=template,
            template_segments_total=0,
            segments_applied=0,
            segments_failed=0,
            kept_elements=len(target_elements),
            total_elements=len(target_elements),
            fallback_reason="no-template",
        )

    from docx import Document

    template_doc = Document(template.file.path)
    segments = build_template_segments(template_doc, template.begin_marker, template.end_marker)
    if not segments:
        return target_elements, SlicingDebugInfo(
            selected_template=template,
            template_segments_total=0,
            segments_applied=0,
            segments_failed=0,
            kept_elements=len(target_elements),
            total_elements=len(target_elements),
            fallback_reason="no-segments-detected",
        )

    sliced_elements, applied_segments, failed_segments = apply_template_segments(target_elements, segments)
    if applied_segments == 0:
        kept = target_elements
        fallback_reason = "no-segments-applied"
    else:
        kept = sliced_elements
        fallback_reason = None

    return kept, SlicingDebugInfo(
        selected_template=template,
        template_segments_total=len(segments),
        segments_applied=applied_segments,
        segments_failed=failed_segments,
        kept_elements=len(kept),
        total_elements=len(target_elements),
        fallback_reason=fallback_reason,
    )
