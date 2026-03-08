from django.urls import path

from apps.analysis_app.views import (
    AnalysisDebugZipView,
    AnalysisDetailView,
    AnalysisEventDetailView,
    AnalysisEventsListView,
    AnalysisQueueStatusView,
    AnalysisQueueView,
    AnalysisStatusView,
    PendingRunsStartAllView,
    PendingRunsDeleteAllView,
    PendingRunCancelView,
    AnalysisRunDeleteView,
    TemplatePreviewView,
    UploadView,
)

urlpatterns = [
    path("upload/", UploadView.as_view(), name="analysis-upload"),
    path("analysis/<uuid:run_id>/", AnalysisDetailView.as_view(), name="analysis-detail"),
    path("analysis/<uuid:run_id>/events/", AnalysisEventsListView.as_view(), name="analysis-events-list"),
    path("analysis/<uuid:run_id>/event/<int:idx>/", AnalysisEventDetailView.as_view(), name="analysis-event-detail"),
    path("analysis/<uuid:run_id>/debug.zip", AnalysisDebugZipView.as_view(), name="analysis-debug-zip"),
    path("analysis/status/<uuid:run_id>/", AnalysisStatusView.as_view(), name="analysis-status"),
    path("analysis/queue/", AnalysisQueueView.as_view(), name="analysis-queue"),
    path("analysis/queue/status/", AnalysisQueueStatusView.as_view(), name="analysis-queue-status"),
    path("analysis/templates/<uuid:template_id>/preview/", TemplatePreviewView.as_view(), name="analysis-template-preview"),
    path("analysis/pu/<str:pu_id>/template/preview/", TemplatePreviewView.as_view(), name="analysis-template-preview-by-pu"),
    path("run/<uuid:run_id>/cancel/", PendingRunCancelView.as_view(), name="analysis-run-cancel"),
    path("analysis/pending/start_all/", PendingRunsStartAllView.as_view(), name="analysis-pending-start-all"),
    path("analysis/pending/delete_all/", PendingRunsDeleteAllView.as_view(), name="analysis-pending-delete-all"),
    path("analysis/<uuid:run_id>/delete/", AnalysisRunDeleteView.as_view(), name="analysis-run-delete"),
]
