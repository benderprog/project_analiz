import logging
import os
import uuid

from django import forms

from apps.analysis_app.document_parsers import DocumentExtractionError, extract_document_text
from apps.analysis_app.models import CachedPU

logger = logging.getLogger(__name__)


GENERAL_SUMMARY_PU_LABEL = "Общая сводка"
SUPPORTED_UPLOAD_EXTENSIONS = {".docx", ".odt", ".rtf", ".pdf"}
SUPPORTED_UPLOAD_ACCEPT = ".docx,.odt,.rtf,.pdf"


def is_general_summary_pu(selected_pu_id: str | uuid.UUID | None) -> bool:
    if selected_pu_id is None:
        return True
    normalized = str(selected_pu_id).strip().lower()
    return normalized in {"", "general"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        parent_clean = super().clean
        if data is None:
            return []
        if isinstance(data, (list, tuple)):
            cleaned_files = []
            for item in data:
                cleaned_files.append(parent_clean(item, initial))
            return cleaned_files
        return [parent_clean(data, initial)]


class UploadDocxForm(forms.Form):
    file = MultipleFileField(
        label="Файл сводки",
        required=True,
        widget=MultipleFileInput(attrs={"multiple": True, "accept": SUPPORTED_UPLOAD_ACCEPT}),
    )

    def clean_file(self):
        files = self.cleaned_data["file"]
        for uploaded_file in files:
            ext = os.path.splitext(uploaded_file.name or "")[1].lower()
            if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
                raise forms.ValidationError(
                    f"Файл {uploaded_file.name} не поддерживается. Допустимые форматы: DOCX, ODT, RTF, PDF."
                )
            try:
                extract_document_text(uploaded_file, filename=uploaded_file.name)
            except DocumentExtractionError as exc:
                raise forms.ValidationError(f"Файл {uploaded_file.name}: {exc}") from exc
            finally:
                uploaded_file.seek(0)
        return files


def get_pu_choices() -> list[tuple[str, str]]:
    choices = [
        (str(pu.portal_pu_id), str(pu.full_name or pu.short_name or ""))
        for pu in CachedPU.objects.order_by("short_name", "full_name")
    ]
    if choices:
        return choices

    from apps.portaldb.gateway import get_portal_gateway

    gateway = get_portal_gateway()
    return [
        (str(pu.pu_id), str(pu.full_name or pu.short_name or ""))
        for pu in gateway.list_pus()
    ]


class UploadDocxWithPuForm(UploadDocxForm):
    selected_pu_id = forms.ChoiceField(
        label="Пограничное управление",
        required=False,
        initial="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected_pu_id"].choices = [("", GENERAL_SUMMARY_PU_LABEL), *get_pu_choices()]


class PuSelectionForm(forms.Form):
    upload_id = forms.UUIDField(widget=forms.HiddenInput)
    selected_pu_id = forms.ChoiceField(
        label="Пограничное управление",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        available_pu_choices = kwargs.pop("pu_choices", None)
        super().__init__(*args, **kwargs)
        if available_pu_choices is None:
            available_pu_choices = get_pu_choices()
        self.fields["selected_pu_id"].choices = [("", GENERAL_SUMMARY_PU_LABEL), *available_pu_choices]

    def clean_selected_pu_id(self):
        value = self.cleaned_data.get("selected_pu_id")
        if is_general_summary_pu(value):
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            logger.debug("Invalid PU selection value %s; treating as general summary.", value)
            return None
