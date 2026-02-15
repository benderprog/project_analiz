from django import forms

from apps.analysis_app.models import PortalDbConnectionSettings


class PortalDbConnectionSettingsAdminForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        label="Пароль",
        widget=forms.PasswordInput(render_value=False, attrs={"placeholder": "********"}),
    )

    class Meta:
        model = PortalDbConnectionSettings
        fields = ("profile", "host", "port", "db_name", "user", "password")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.password_encrypted:
            self.fields["password"].help_text = (
                "Пароль задан (********). Оставьте поле пустым, чтобы не менять."
            )

    def save(self, commit=True):
        raise RuntimeError("Use PortalDbConnectionSettingsAdmin.save_model()")
