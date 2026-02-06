import uuid

from django.conf import settings
from django.db import models


class AnalysisRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    file = models.FileField(upload_to="uploads/")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    def __str__(self) -> str:
        return f"Run {self.run_id}"


class AnalysisParagraph(models.Model):
    run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name="paragraphs")
    idx = models.PositiveIntegerField()
    text = models.TextField()

    def __str__(self) -> str:
        return f"Paragraph {self.idx}"


class AnalysisResult(models.Model):
    paragraph = models.OneToOneField(
        AnalysisParagraph, on_delete=models.CASCADE, related_name="result"
    )
    extracted_attributes = models.JSONField(default=dict)
    match_result = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f"Result for {self.paragraph_id}"
