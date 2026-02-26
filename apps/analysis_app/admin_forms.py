from django import forms

from apps.analysis_app.forms import GENERAL_SUMMARY_PU_LABEL
from apps.analysis_app.models import FeatureFlags, PortalDbConnectionSettings, SvodkaTemplate
from apps.portaldb.gateway import get_portal_gateway


GENERAL_PU_CHOICE_VALUE = "__GENERAL__"


class PortalDbConnectionSettingsAdminForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        label="Пароль",
        widget=forms.PasswordInput(render_value=False, attrs={"placeholder": "********"}),
    )
    debug_mode = forms.BooleanField(required=False, label="DEBUG mode")

    class Meta:
        model = PortalDbConnectionSettings
        fields = ("profile", "host", "port", "db_name", "user", "password")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.password_encrypted:
            self.fields["password"].help_text = (
                "Пароль сохранён. Оставьте пустым, чтобы не менять."
            )
        if not self.is_bound:
            self.fields["debug_mode"].initial = FeatureFlags.is_debug_enabled()

    def save(self, commit=True):
        obj = super().save(commit=False)
        if commit:
            obj.save()
            flags = FeatureFlags.get_solo()
            flags.debug_mode = bool(self.cleaned_data.get("debug_mode", False))
            flags.save(update_fields=["debug_mode", "updated_at"])
        return obj


class SvodkaTemplateAdminForm(forms.ModelForm):
    pu_select = forms.ChoiceField(label="Пограничное управление:", required=True)

    class Meta:
        model = SvodkaTemplate
        fields = ("pu_select", "file", "begin_marker", "end_marker", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pu_name_map: dict[str, str] = {}
        self.fields["pu_select"].choices = self._build_pu_choices()

        if self.instance and self.instance.pk:
            if self.instance.scope == SvodkaTemplate.Scope.GENERAL or not self.instance.pu_id:
                self.fields["pu_select"].initial = GENERAL_PU_CHOICE_VALUE
            else:
                self.fields["pu_select"].initial = str(self.instance.pu_id)
        else:
            self.fields["pu_select"].initial = GENERAL_PU_CHOICE_VALUE

    def _build_pu_choices(self):
        choices = [
            (GENERAL_PU_CHOICE_VALUE, GENERAL_SUMMARY_PU_LABEL),
        ]
        try:
            gateway = get_portal_gateway()
            for pu in gateway.list_pus():
                pu_id = str(pu.pu_id)
                pu_name = str(pu.full_name or pu.short_name or "")
                self._pu_name_map[pu_id] = pu_name
                choices.append((pu_id, pu_name))
        except Exception:  # noqa: BLE001
            pass
        return choices

    def clean(self):
        cleaned_data = super().clean()
        pu_select = cleaned_data.get("pu_select")

        resolved_scope = SvodkaTemplate.Scope.GENERAL
        resolved_pu_id = ""
        resolved_pu_name = GENERAL_SUMMARY_PU_LABEL

        if pu_select == GENERAL_PU_CHOICE_VALUE:
            resolved_scope = SvodkaTemplate.Scope.GENERAL
            resolved_pu_id = ""
            resolved_pu_name = GENERAL_SUMMARY_PU_LABEL
        else:
            resolved_scope = SvodkaTemplate.Scope.PU
            resolved_pu_id = str(pu_select)
            resolved_pu_name = self._pu_name_map.get(resolved_pu_id, "")

        cleaned_data["scope"] = resolved_scope
        cleaned_data["pu_id"] = resolved_pu_id
        cleaned_data["pu_name"] = resolved_pu_name
        return cleaned_data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.scope = self.cleaned_data.get("scope", obj.scope)
        obj.pu_id = self.cleaned_data.get("pu_id", obj.pu_id)
        obj.pu_name = self.cleaned_data.get("pu_name", obj.pu_name)
        if commit:
            obj.save()
        return obj
