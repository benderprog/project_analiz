import logging

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from apps.classifier.importer import import_classifier_rows, parse_classifier_xlsx
from apps.classifier.models import EventType, EventTypePattern

logger = logging.getLogger(__name__)


class ClassifierImportForm(forms.Form):
    xlsx_file = forms.FileField(label="XLSX файл")
    clear_before = forms.BooleanField(
        required=False,
        label="Очистить перед импортом",
        help_text="Удалить текущий классификатор перед загрузкой.",
    )


class EventTypePatternInline(admin.TabularInline):
    model = EventTypePattern
    extra = 1
    fields = ("pattern", "article_of_law")


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ("event_type", "patterns_count")
    search_fields = ("event_type", "patterns__pattern")
    inlines = [EventTypePatternInline]
    change_list_template = "admin/classifier/eventtype/change_list.html"

    @admin.display(description="Patterns")
    def patterns_count(self, obj):
        return obj.patterns.count()

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
                rows, skipped_rows = parse_classifier_xlsx(xlsx_file)
                summary = import_classifier_rows(
                    rows,
                    clear_before=clear_before,
                    skipped_rows=skipped_rows,
                )
                messages.success(
                    request,
                    (
                        "Импорт завершен: "
                        f"создано типов {summary.created_types}, "
                        f"паттернов {summary.created_patterns}, "
                        f"обновлено статей {summary.updated_patterns}, "
                        f"пропущено строк {summary.skipped_rows}."
                    ),
                )
                logger.info(
                    "Classifier import completed: %s",
                    summary,
                )
                return redirect("..")
        else:
            form = ClassifierImportForm()

        return render(
            request,
            "admin/classifier/import_xlsx.html",
            {"form": form},
        )
