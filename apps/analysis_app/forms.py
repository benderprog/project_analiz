import logging
import os
import uuid

from django import forms

from apps.analysis_app.models import CachedPU

logger = logging.getLogger(__name__)


GENERAL_SUMMARY_PU_LABEL = "Общая сводка"


def is_general_summary_pu(selected_pu_id: str | uuid.UUID | None) -> bool:
    if selected_pu_id is None:
        return True
    normalized = str(selected_pu_id).strip().lower()
    return normalized in {"", "general"}


class UploadDocxForm(forms.Form):
    file = forms.FileField(
        label="DOCX файл",
        required=False,
        widget=forms.FileInput(attrs={"multiple": True}),
    )

    def clean(self):
        cleaned_data = super().clean()
        files = self.files.getlist("file")
        if not files:
            self.add_error("file", "Выберите хотя бы один DOCX файл.")
            return cleaned_data

        for uploaded_file in files:
            ext = os.path.splitext(uploaded_file.name or "")[1].lower()
            if ext != ".docx":
                self.add_error("file", f"Файл {uploaded_file.name} должен быть в формате DOCX.")

        if self.errors.get("file"):
            return cleaned_data

        cleaned_data["files"] = files
        cleaned_data["file"] = files[0]
        return cleaned_data


class PuSelectionForm(forms.Form):
    upload_id = forms.UUIDField(widget=forms.HiddenInput)
    selected_pu_id = forms.ChoiceField(
        label="Пограничное управление",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        pu_choices = kwargs.pop("pu_choices", None)
        super().__init__(*args, **kwargs)
        if pu_choices is None:
            pu_choices = []
            for pu in CachedPU.objects.order_by("short_name", "full_name"):
                label = str(pu.full_name or pu.short_name or "")
                pu_choices.append((str(pu.portal_pu_id), label))
        self.fields["selected_pu_id"].choices = [("", GENERAL_SUMMARY_PU_LABEL), *pu_choices]

    def clean_selected_pu_id(self):
        value = self.cleaned_data.get("selected_pu_id")
        if is_general_summary_pu(value):
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            logger.debug("Invalid PU selection value %s; treating as general summary.", value)
            return None
