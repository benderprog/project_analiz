from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree
from zipfile import ZipFile

SUPPORTED_FORMATS = {".docx", ".odt", ".rtf", ".pdf"}

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_ODT_NS = {
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}


class DocumentExtractionError(Exception):
    pass


class UnsupportedDocumentFormatError(DocumentExtractionError):
    pass


class PdfTextLayerMissingError(DocumentExtractionError):
    pass


@dataclass(slots=True)
class ExtractedDocument:
    source_format: str
    text: str
    lines: list[str]
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    is_text_based: bool = True


def detect_document_format(path: str | Path | None = None, *, filename: str | None = None) -> str:
    candidate = filename or (str(path) if path is not None else "")
    ext = Path(candidate).suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise UnsupportedDocumentFormatError(
            "Unsupported document format. Supported formats: docx, odt, rtf, pdf."
        )
    return ext.lstrip(".")


def extract_document_text(path_or_file: str | Path | BinaryIO, *, filename: str | None = None) -> ExtractedDocument:
    if isinstance(path_or_file, (str, Path)):
        source_format = detect_document_format(path_or_file)
    else:
        source_format = detect_document_format(filename=filename)

    if source_format == "docx":
        return _extract_docx(path_or_file)
    if source_format == "odt":
        return _extract_odt(path_or_file)
    if source_format == "rtf":
        return _extract_rtf(path_or_file)
    return _extract_pdf(path_or_file)


def _read_bytes(source: str | Path | BinaryIO) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    source.seek(0)
    data = source.read()
    source.seek(0)
    return data if isinstance(data, bytes) else str(data).encode("utf-8", errors="ignore")


def _extract_docx(source: str | Path | BinaryIO) -> ExtractedDocument:
    raw = _read_bytes(source)
    with ZipFile(Path(source) if isinstance(source, (str, Path)) else source) as archive:
        xml_content = archive.read("word/document.xml")

    root = ElementTree.fromstring(xml_content)
    lines: list[str] = []
    for paragraph in root.findall(".//w:p", _DOCX_NS):
        chunks = [node.text or "" for node in paragraph.findall(".//w:t", _DOCX_NS)]
        value = "".join(chunks).strip()
        if value:
            lines.append(value)

    return ExtractedDocument("docx", "\n".join(lines), lines, meta={"byte_size": len(raw), "line_count": len(lines)})


def _extract_odt(source: str | Path | BinaryIO) -> ExtractedDocument:
    raw = _read_bytes(source)
    with ZipFile(Path(source) if isinstance(source, (str, Path)) else source) as archive:
        xml_content = archive.read("content.xml")

    root = ElementTree.fromstring(xml_content)
    lines: list[str] = []
    for tag in ("text:h", "text:p"):
        for node in root.findall(f".//{tag}", _ODT_NS):
            value = "".join(node.itertext()).strip()
            if value:
                lines.append(value)

    return ExtractedDocument("odt", "\n".join(lines), lines, meta={"byte_size": len(raw), "line_count": len(lines)})


def _extract_rtf(source: str | Path | BinaryIO) -> ExtractedDocument:
    raw = _read_bytes(source)
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        decoded = raw.decode("latin1", errors="ignore")
    text = _rtf_to_text(decoded)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ExtractedDocument("rtf", "\n".join(lines), lines, meta={"line_count": len(lines)})


def _extract_pdf(source: str | Path | BinaryIO) -> ExtractedDocument:
    raw = _read_bytes(source)
    lines: list[str] = []
    page_count = None

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(source)
        page_count = len(reader.pages)
        for page in reader.pages:
            page_text = (page.extract_text() or "").strip()
            if page_text:
                lines.extend(line.strip() for line in page_text.splitlines() if line.strip())
    except Exception:
        lines = _extract_pdf_text_naive(raw)

    if not lines:
        raise PdfTextLayerMissingError(
            "PDF does not contain an extractable text layer. Scanned/image-only PDF is not supported yet."
        )

    return ExtractedDocument(
        "pdf",
        "\n".join(lines),
        lines,
        meta={"line_count": len(lines), "page_count": page_count},
        is_text_based=True,
    )


def _extract_pdf_text_naive(raw: bytes) -> list[str]:
    lines: list[str] = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw, flags=re.DOTALL):
        data = stream
        try:
            data = zlib.decompress(stream)
        except Exception:
            pass
        for part in re.findall(rb"\((.*?)\)\s*Tj", data, flags=re.DOTALL):
            value = _decode_pdf_literal_string(part)
            if value.strip():
                lines.append(value.strip())
    return lines


def _decode_pdf_literal_string(raw: bytes) -> str:
    text = raw.decode("latin1", errors="ignore")
    text = re.sub(r"\\([()\\])", r"\1", text)
    text = re.sub(r"\\[nrtbf]", " ", text)
    text = re.sub(r"\\\d{1,3}", "", text)
    return text


def _rtf_to_text(rtf: str) -> str:
    rtf = re.sub(r"{\\fonttbl.*?}", "", rtf, flags=re.DOTALL)
    rtf = re.sub(r"\\par[d]?", "\n", rtf)
    rtf = re.sub(r"\\'[0-9a-fA-F]{2}", "", rtf)
    rtf = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", rtf)
    rtf = re.sub(r"[{}]", "", rtf)
    rtf = rtf.replace("\\", "")
    return "\n".join(line.strip() for line in rtf.splitlines())
