from django.urls import path

from apps.analysis_app.views import AnalysisDetailView, UploadView

urlpatterns = [
    path("upload/", UploadView.as_view(), name="analysis-upload"),
    path("analysis/<uuid:run_id>/", AnalysisDetailView.as_view(), name="analysis-detail"),
]
