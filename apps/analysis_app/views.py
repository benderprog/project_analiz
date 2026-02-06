from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.analysis_app.forms import UploadDocxForm
from apps.analysis_app.models import AnalysisParagraph, AnalysisResult, AnalysisRun
from apps.analysis_app.services import extract_attributes, match_event, parse_docx


class UploadView(View):
    template_name = "analysis_app/upload.html"

    def get(self, request):
        return render(request, self.template_name, {"form": UploadDocxForm()})

    def post(self, request):
        form = UploadDocxForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        run = AnalysisRun.objects.create(
            uploaded_by=request.user if request.user.is_authenticated else None,
            file=form.cleaned_data["file"],
        )
        try:
            paragraphs = parse_docx(run.file.path)
            for idx, text in enumerate(paragraphs, start=1):
                paragraph = AnalysisParagraph.objects.create(run=run, idx=idx, text=text)
                attributes = extract_attributes(text)
                match_result = match_event(attributes, text)
                AnalysisResult.objects.create(
                    paragraph=paragraph,
                    extracted_attributes={
                        "date_time": attributes.date_time.isoformat()
                        if attributes.date_time
                        else None,
                        "subdivision_id": attributes.subdivision_id,
                        "subdivision_name": attributes.subdivision_name,
                        "offenders": attributes.offenders,
                    },
                    match_result=match_result,
                )
            run.status = AnalysisRun.Status.COMPLETED
            run.save(update_fields=["status"])
        except Exception as exc:  # noqa: BLE001 - capture for status update
            run.status = AnalysisRun.Status.FAILED
            run.save(update_fields=["status"])
            messages.error(request, f"Ошибка анализа: {exc}")
            return redirect("analysis-upload")

        return redirect("analysis-detail", run_id=run.run_id)


class AnalysisDetailView(View):
    template_name = "analysis_app/detail.html"

    def get(self, request, run_id):
        run = get_object_or_404(AnalysisRun, run_id=run_id)
        paragraphs = run.paragraphs.select_related("result").order_by("idx")
        return render(
            request,
            self.template_name,
            {"run": run, "paragraphs": paragraphs},
        )
