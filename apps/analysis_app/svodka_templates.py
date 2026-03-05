from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from django.conf import settings

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
    end_anchor_text: str | None = None
    is_open_ended: bool = False
    weak_start_anchor: bool = False
    weak_end_anchor: bool = False
    index: int = 0


@dataclass(frozen=True)
class MarkerBlock:
    begin_marker_span: tuple[int, int]
    end_marker_span: tuple[int, int] | None
    pre_anchor_text: str | None
    post_anchor_text: str | None
    index: int
    weak_pre_anchor: bool = False
    weak_post_anchor: bool = False


@dataclass(frozen=True)
class SlicingDebugInfo:
    selected_template: SvodkaTemplate | None
    template_segments_total: int
    segments_applied: int
    segments_failed: int
    kept_elements: int
    total_elements: int
    target_markers_found: bool = False
    target_segments_count: int = 0
    target_kept_elements: int = 0
    fallback_reason: str | None = None
    slicing_strategy: str = "none"
    segment_matches: list[dict[str, Any]] | None = None
    warnings: list[str] | None = None
    template_anchor_threshold: float | None = None


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
ANCHOR_MIN_CHARS = 10
START_MIN_SIM = float(getattr(settings, "TEMPLATE_ANCHOR_START_MIN_SIM", 0.60))
END_MIN_SIM = float(getattr(settings, "TEMPLATE_ANCHOR_END_MIN_SIM", 0.60))
WEAK_ANCHOR_MIN_SIM = float(getattr(settings, "TEMPLATE_ANCHOR_WEAK_MIN_SIM", 0.85))
MAX_ANCHOR_LINE_DISTANCE = int(getattr(settings, "TEMPLATE_ANCHOR_MAX_LINE_DISTANCE", 400))


def _normalize_ws(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize_anchor_text(text: str) -> str:
    normalized = (text or "").lower().replace("ё", "е")
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _anchor_details(text: str | None, begin_marker: str, end_marker: str) -> tuple[str | None, bool]:
    cleaned = _normalize_ws(text)
    if begin_marker:
        cleaned = re.sub(re.escape(begin_marker), " ", cleaned, flags=re.IGNORECASE)
    if end_marker:
        cleaned = re.sub(re.escape(end_marker), " ", cleaned, flags=re.IGNORECASE)
    normalized = normalize_anchor_text(cleaned)
    if not normalized:
        return None, True
    return normalized, len(normalized) < ANCHOR_MIN_CHARS


def _line_ranges(text: str) -> list[tuple[int, int, str]]:
    lines = text.splitlines(keepends=True)
    ranges: list[tuple[int, int, str]] = []
    cursor = 0
    for line in lines:
        start = cursor
        cursor += len(line)
        ranges.append((start, cursor, line.rstrip("\n\r")))
    if not lines:
        ranges.append((0, 0, ""))
    return ranges


def parse_template_marker_blocks(template_text: str, begin_marker: str = "[BEGIN]", end_marker: str = "[END]") -> tuple[list[MarkerBlock], list[str]]:
    if not template_text or not begin_marker:
        return [], []

    line_ranges = _line_ranges(template_text)
    begins = [(m.start(), m.end(), "BEGIN") for m in re.finditer(re.escape(begin_marker), template_text, flags=re.IGNORECASE)]
    ends = [(m.start(), m.end(), "END") for m in re.finditer(re.escape(end_marker), template_text, flags=re.IGNORECASE)] if end_marker else []
    markers = sorted([*begins, *ends], key=lambda x: (x[0], 0 if x[2] == "BEGIN" else 1))

    blocks: list[MarkerBlock] = []
    warnings: list[str] = []
    active_begin: tuple[int, int] | None = None

    def _line_idx(offset: int) -> int:
        for idx, (start, finish, _) in enumerate(line_ranges):
            if start <= offset < max(finish, start + 1):
                return idx
        return max(len(line_ranges) - 1, 0)

    def _nearest_nonempty_before(idx: int) -> str | None:
        for p in range(idx, -1, -1):
            value = _normalize_ws(line_ranges[p][2])
            if value:
                return value
        return None

    def _nearest_nonempty_after(idx: int) -> str | None:
        for p in range(idx, len(line_ranges)):
            value = _normalize_ws(line_ranges[p][2])
            if value:
                return value
        return None

    for start, finish, kind in markers:
        if kind == "BEGIN":
            if active_begin is not None:
                warnings.append("BEGIN without END before next BEGIN; previous block treated as open-ended")
                begin_line = _line_idx(active_begin[0])
                pre_anchor_text, weak_pre = _anchor_details(_nearest_nonempty_before(begin_line - 1), begin_marker, end_marker)
                blocks.append(
                    MarkerBlock(
                        begin_marker_span=active_begin,
                        end_marker_span=None,
                        pre_anchor_text=pre_anchor_text,
                        post_anchor_text=None,
                        index=len(blocks),
                        weak_pre_anchor=weak_pre,
                    )
                )
            active_begin = (start, finish)
            continue

        if active_begin is None:
            warnings.append("END without BEGIN ignored")
            continue

        begin_line = _line_idx(active_begin[0])
        end_line = _line_idx(start)
        pre_anchor_text, weak_pre = _anchor_details(_nearest_nonempty_before(begin_line - 1), begin_marker, end_marker)
        post_anchor_text, weak_post = _anchor_details(_nearest_nonempty_after(end_line + 1), begin_marker, end_marker)
        blocks.append(
            MarkerBlock(
                begin_marker_span=active_begin,
                end_marker_span=(start, finish),
                pre_anchor_text=pre_anchor_text,
                post_anchor_text=post_anchor_text,
                index=len(blocks),
                weak_pre_anchor=weak_pre,
                weak_post_anchor=weak_post,
            )
        )
        active_begin = None

    if active_begin is not None:
        begin_line = _line_idx(active_begin[0])
        pre_anchor_text, weak_pre = _anchor_details(_nearest_nonempty_before(begin_line - 1), begin_marker, end_marker)
        blocks.append(
            MarkerBlock(
                begin_marker_span=active_begin,
                end_marker_span=None,
                pre_anchor_text=pre_anchor_text,
                post_anchor_text=None,
                index=len(blocks),
                weak_pre_anchor=weak_pre,
            )
        )
        warnings.append("BEGIN without END treated as open-ended")

    return blocks, warnings


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


def _replace_markers(text: str, marker: str) -> str:
    if not marker:
        return text
    return re.sub(re.escape(marker), " ", text, flags=re.IGNORECASE)


def _clean_element_text(element: DocElement, cleaned_text: str) -> DocElement:
    return DocElement(
        kind=element.kind,
        text=cleaned_text,
        cells=element.cells,
        table_header_cells=element.table_header_cells,
        is_table_header=element.is_table_header,
    )


def slice_by_markers(
    elements: Sequence[DocElement], begin: str = "[BEGIN]", end: str = "[END]"
) -> tuple[list[DocElement], dict[str, int | bool]]:
    begin_l = (begin or "").lower()
    end_l = (end or "").lower()

    if not begin_l or not end_l:
        return [], {"markers_found": False, "segments_count": 0, "kept_elements": 0}

    active = False
    segments_count = 0
    markers_found = False
    kept: list[DocElement] = []

    for element in elements:
        text = element.text
        lowered = text.lower()
        has_begin = begin_l in lowered
        has_end = end_l in lowered

        if has_begin:
            markers_found = True
            if not active:
                segments_count += 1
            active = True

        should_keep = active
        if has_end:
            markers_found = True

        if should_keep:
            cleaned = _normalize_ws(_replace_markers(_replace_markers(text, begin), end))
            if cleaned:
                kept.append(_clean_element_text(element, cleaned))

        if has_end and active:
            active = False

    return kept, {
        "markers_found": markers_found,
        "segments_count": segments_count,
        "kept_elements": len(kept),
    }


def build_template_segments(template_doc, begin_marker: str, end_marker: str) -> list[SegmentAnchors]:
    texts = _element_texts_for_segments(template_doc)
    if not begin_marker:
        return []
    blocks, _ = parse_template_marker_blocks("\n".join(texts), begin_marker=begin_marker, end_marker=end_marker)
    segments: list[SegmentAnchors] = []
    for block in blocks:
        segments.append(
            SegmentAnchors(
                start_anchor_text=block.pre_anchor_text or "",
                end_anchor_text=block.post_anchor_text,
                is_open_ended=block.end_marker_span is None,
                weak_start_anchor=block.weak_pre_anchor,
                weak_end_anchor=block.weak_post_anchor,
                index=block.index,
            )
        )
    return segments


def _lexical_similarity(anchor: str, text: str) -> float:
    a = normalize_anchor_text(anchor)
    b = normalize_anchor_text(text)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if not norm_a or not norm_b:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _get_semantic_vectors(texts: Sequence[str]) -> list[list[float]] | None:
    try:
        from apps.analysis_app.semantic import get_sentence_model

        model = get_sentence_model() if not settings.SKIP_SEMANTIC_MODEL else None
    except Exception as exc:  # noqa: BLE001
        logger.info("Semantic model unavailable, using lexical anchor fallback: %s", exc)
        return None

    if not model:
        return None

    encoded = model.encode(list(texts))
    return [list(row) for row in encoded]


def _find_best_anchor_index(
    anchor: str,
    target_elements: Sequence[DocElement],
    *,
    start_from: int = 0,
    min_score: float,
    weak_anchor: bool,
    semantic_anchor_vec: Sequence[float] | None,
    semantic_element_vecs: Sequence[Sequence[float]] | None,
) -> tuple[int | None, float, float]:
    best_idx: int | None = None
    best_score = 0.0
    if weak_anchor or semantic_anchor_vec is None or semantic_element_vecs is None:
        for idx in range(start_from, len(target_elements)):
            score = _lexical_similarity(anchor, target_elements[idx].text)
            if score > best_score:
                best_score = score
                best_idx = idx
    else:
        for idx in range(start_from, len(target_elements)):
            score = _cosine_similarity(semantic_anchor_vec, semantic_element_vecs[idx])
            if score > best_score:
                best_score = score
                best_idx = idx

    threshold = WEAK_ANCHOR_MIN_SIM if weak_anchor else min_score
    if best_idx is None or best_score < threshold:
        return None, best_score, threshold
    return best_idx, best_score, threshold


def apply_template_segments(
    target_elements: Sequence[DocElement],
    segment_anchors: Sequence[SegmentAnchors],
    *,
    base_threshold: float = START_MIN_SIM,
) -> tuple[list[DocElement], int, int, list[dict[str, Any]], list[str]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    failed_segments = 0
    debug_segments: list[dict[str, Any]] = []
    warnings: list[str] = []

    element_texts = [element.text for element in target_elements]
    anchor_texts = [anchor.start_anchor_text for anchor in segment_anchors if anchor.start_anchor_text]
    anchor_texts.extend([anchor.end_anchor_text for anchor in segment_anchors if anchor.end_anchor_text])
    semantic_texts = [*element_texts, *anchor_texts]
    semantic_vectors = _get_semantic_vectors(semantic_texts) if semantic_texts else None
    semantic_element_vecs = semantic_vectors[: len(element_texts)] if semantic_vectors else None
    anchor_vec_map = {
        text: semantic_vectors[len(element_texts) + idx]
        for idx, text in enumerate(anchor_texts)
    } if semantic_vectors else {}

    for segment in segment_anchors:
        debug_item = {"index": segment.index, "start_idx": None, "end_idx": None, "start_score": 0.0, "end_score": 0.0, "start_threshold": None, "end_threshold": None, "start_status": "rejected", "end_status": "rejected"}
        if not segment.start_anchor_text:
            warnings.append(f"segment {segment.index}: missing start anchor")
            failed_segments += 1
            debug_segments.append(debug_item)
            continue

        start_idx, start_score, start_threshold = _find_best_anchor_index(
            segment.start_anchor_text,
            target_elements,
            start_from=cursor,
            min_score=base_threshold,
            weak_anchor=segment.weak_start_anchor,
            semantic_anchor_vec=anchor_vec_map.get(segment.start_anchor_text),
            semantic_element_vecs=semantic_element_vecs,
        )
        debug_item["start_idx"] = start_idx
        debug_item["start_score"] = round(float(start_score), 4)
        debug_item["start_threshold"] = round(float(start_threshold), 4)
        if start_idx is None:
            warnings.append(f"segment {segment.index}: start anchor below threshold {start_threshold:.2f}")
            failed_segments += 1
            debug_segments.append(debug_item)
            continue

        debug_item["start_status"] = "accepted"

        if segment.is_open_ended or not segment.end_anchor_text:
            ranges.append((start_idx + 1, len(target_elements) - 1))
            debug_item["end_idx"] = len(target_elements) - 1
            debug_item["open_ended"] = True
            cursor = len(target_elements)
            debug_segments.append(debug_item)
            continue

        end_idx, end_score, end_threshold = _find_best_anchor_index(
            segment.end_anchor_text,
            target_elements,
            start_from=start_idx + 1,
            min_score=base_threshold,
            weak_anchor=segment.weak_end_anchor,
            semantic_anchor_vec=anchor_vec_map.get(segment.end_anchor_text),
            semantic_element_vecs=semantic_element_vecs,
        )
        debug_item["end_idx"] = end_idx
        debug_item["end_score"] = round(float(end_score), 4)
        debug_item["end_threshold"] = round(float(end_threshold), 4)
        if end_idx is None:
            warnings.append(f"segment {segment.index}: end anchor below threshold {end_threshold:.2f}, sliced to end")
            ranges.append((start_idx + 1, len(target_elements) - 1))
            cursor = len(target_elements)
            debug_item["open_ended"] = True
            debug_segments.append(debug_item)
            continue

        debug_item["end_status"] = "accepted"

        if (end_idx - start_idx) > MAX_ANCHOR_LINE_DISTANCE:
            warnings.append(f"segment {segment.index}: large span ({end_idx - start_idx} lines)")

        ranges.append((start_idx + 1, end_idx - 1))
        cursor = end_idx + 1
        debug_segments.append(debug_item)

    if not ranges:
        return [], 0, failed_segments, debug_segments, warnings

    ranges.sort(key=lambda pair: pair[0])
    merged: list[list[int]] = [[ranges[0][0], ranges[0][1]]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    sliced: list[DocElement] = []
    for start, end in merged:
        if start <= end:
            sliced.extend(target_elements[start : end + 1])
    return sliced, len(ranges), failed_segments, debug_segments, warnings


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
            target_markers_found=False,
            target_segments_count=0,
            target_kept_elements=0,
            fallback_reason="no-template",
            slicing_strategy="none",
            template_anchor_threshold=None,
        )

    marker_sliced, marker_debug = slice_by_markers(target_elements, template.begin_marker, template.end_marker)
    if marker_debug["markers_found"] and marker_debug["kept_elements"] > 0:
        return marker_sliced, SlicingDebugInfo(
            selected_template=template,
            template_segments_total=0,
            segments_applied=0,
            segments_failed=0,
            kept_elements=len(marker_sliced),
            total_elements=len(target_elements),
            target_markers_found=bool(marker_debug["markers_found"]),
            target_segments_count=int(marker_debug["segments_count"]),
            target_kept_elements=int(marker_debug["kept_elements"]),
            fallback_reason=None,
            slicing_strategy="report_markers",
            template_anchor_threshold=float(template.anchor_match_threshold or START_MIN_SIM),
        )

    from docx import Document

    template_doc = Document(template.file.path)
    segments = build_template_segments(template_doc, template.begin_marker, template.end_marker)
    template_threshold = float(template.anchor_match_threshold or START_MIN_SIM)
    if not segments:
        return target_elements, SlicingDebugInfo(
            selected_template=template,
            template_segments_total=0,
            segments_applied=0,
            segments_failed=0,
            kept_elements=len(target_elements),
            total_elements=len(target_elements),
            target_markers_found=bool(marker_debug["markers_found"]),
            target_segments_count=int(marker_debug["segments_count"]),
            target_kept_elements=int(marker_debug["kept_elements"]),
            fallback_reason="no-segments-detected",
            slicing_strategy="none",
            template_anchor_threshold=template_threshold,
        )

    sliced_elements, applied_segments, failed_segments, segment_matches, warnings = apply_template_segments(
        target_elements,
        segments,
        base_threshold=template_threshold,
    )
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
        target_markers_found=bool(marker_debug["markers_found"]),
        target_segments_count=int(marker_debug["segments_count"]),
        target_kept_elements=int(marker_debug["kept_elements"]),
        fallback_reason=fallback_reason,
        slicing_strategy="semantic_anchors" if applied_segments else "none",
        segment_matches=segment_matches,
        warnings=warnings,
        template_anchor_threshold=template_threshold,
    )
