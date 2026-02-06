from django import forms


class UploadDocxForm(forms.Form):
    file = forms.FileField(label="DOCX файл")
