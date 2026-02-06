import logging

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from apps.classifier.importer import import_classifier_rows, parse_classifier_xlsx
from apps.classifier.models import EventTypeClassifier

logger = logging.getLogger(__name__)


class ClassifierImportForm(forms.Form):
    xlsx_file = forms.FileField(label="XLSX файл")
    clear_before = forms.BooleanField(
        required=False,
        label="Очистить перед импортом",
        help_text="Удалить текущий классификатор перед загрузкой.",
    )


@admin.register(EventTypeClassifier)
class EventTypeClassifierAdmin(admin.ModelAdmin):
    list_display = ("event_type", "event_pattern", "article_of_law")
    search_fields = ("event_type", "event_pattern", "article_of_law")
    change_list_template = "admin/classifier/eventtypeclassifier/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("import-xlsx/", self.admin_site.admin_view(self.import_xlsx))
        ]
        return custom_urls + urls

    def import_xlsx(self, request):
        if request.method == "POST":
            form = ClassifierImportForm(request.POST, request.FILES)
            if form.is_valid():
                xlsx_file = form.cleaned_data["xlsx_file"]
                clear_before = form.cleaned_data["clear_before"]
                rows = parse_classifier_xlsx(xlsx_file)
                created = import_classifier_rows(rows, clear_before=clear_before)
                messages.success(
                    request,
                    f"Импорт завершен: создано {created} строк(и).",
                )
                logger.info("Classifier import completed: %s rows", created)
                return redirect("..")
        else:
            form = ClassifierImportForm()

        return render(
            request,
            "admin/classifier/import_xlsx.html",
            {"form": form},
        )
