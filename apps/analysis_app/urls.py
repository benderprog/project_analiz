from django.urls import path

from apps.analysis_app.views import (
    AnalysisDetailView,
    AnalysisQueueResetView,
    AnalysisQueueStatusView,
    AnalysisStatusView,
    PendingRunCancelView,
    UploadView,
)

urlpatterns = [
    path("upload/", UploadView.as_view(), name="analysis-upload"),
    path("analysis/<uuid:run_id>/", AnalysisDetailView.as_view(), name="analysis-detail"),
    path("analysis/status/<uuid:run_id>/", AnalysisStatusView.as_view(), name="analysis-status"),
    path("analysis/queue/status/", AnalysisQueueStatusView.as_view(), name="analysis-queue-status"),
    path("queue/reset/", AnalysisQueueResetView.as_view(), name="analysis-queue-reset"),
    path("run/<uuid:run_id>/cancel/", PendingRunCancelView.as_view(), name="analysis-run-cancel"),
]
