import logging
import uuid

from django import forms

from apps.analysis_app.models import CachedPU

logger = logging.getLogger(__name__)


class UploadDocxForm(forms.Form):
    file = forms.FileField(label="DOCX файл")


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
                label_parts = [part for part in [pu.short_name, pu.full_name] if part]
                label = " — ".join(label_parts)
                pu_choices.append((str(pu.portal_pu_id), label))
        self.fields["selected_pu_id"].choices = [("", "Общая сводка"), *pu_choices]

    def clean_selected_pu_id(self):
        value = self.cleaned_data.get("selected_pu_id")
        if not value or value == "general":
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            logger.debug("Invalid PU selection value %s; treating as general summary.", value)
            return None
