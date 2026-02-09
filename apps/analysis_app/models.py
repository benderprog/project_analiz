import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import build_embedding_source_hash, to_py_floats
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text


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


class CachedPU(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal_pu_id = models.UUIDField(unique=True)
    short_name = models.CharField(max_length=255)
    full_name = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cached PU"
        verbose_name_plural = "Cached PUs"

    def __str__(self) -> str:
        return self.short_name or self.full_name


class CachedSubdivision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal_subdivision_id = models.UUIDField(unique=True)
    name = models.CharField(max_length=255)
    pu = models.ForeignKey(CachedPU, null=True, blank=True, on_delete=models.SET_NULL)
    normalized_name = models.TextField()
    legacy_aliases = models.JSONField(blank=True, null=True)
    embedding = models.JSONField(blank=True, null=True)
    embedding_source_hash = models.CharField(max_length=64, blank=True, default="")
    embedding_updated_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cached Subdivision"
        verbose_name_plural = "Cached Subdivisions"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        update_fields = kwargs.get("update_fields")
        embedding_text = getattr(self, "embedding_source_text", None)
        normalized_source = None
        if embedding_text is not None:
            embedding_text = (embedding_text or "").strip()
            normalized_source = normalize_subdivision_text(embedding_text)
        elif self.normalized_name:
            normalized_source = self.normalized_name
        elif self.name:
            normalized_source = normalize_subdivision_text(self.name)

        if normalized_source is not None:
            self.normalized_name = normalized_source

        new_hash = build_embedding_source_hash(self.normalized_name, self.legacy_aliases)
        existing_hash = None
        if self.pk:
            existing_hash = (
                CachedSubdivision.objects.filter(pk=self.pk)
                .values_list("embedding_source_hash", flat=True)
                .first()
            )

        should_rebuild = (
            self._state.adding
            or self.embedding is None
            or (existing_hash is not None and existing_hash != new_hash)
        )
        self.embedding_source_hash = new_hash

        skip_rebuild = getattr(self, "_skip_embedding_rebuild", False)

        if should_rebuild and settings.SKIP_SEMANTIC_MODEL:
            self.embedding = None
            self.embedding_updated_at = None
        elif should_rebuild and not skip_rebuild:
            try:
                model = get_sentence_model()
            except RuntimeError:
                model = None
            if model:
                embedding = model.encode([self.normalized_name])[0]
                self.embedding = to_py_floats(embedding)
                self.embedding_updated_at = timezone.now()

        if update_fields is not None:
            update_fields = set(update_fields)
            update_fields.update({"normalized_name", "embedding_source_hash", "updated_at"})
            if should_rebuild:
                update_fields.update({"embedding", "embedding_updated_at"})
            kwargs["update_fields"] = update_fields

        super().save(*args, **kwargs)


class CachedSubdivisionAlias(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subdivision = models.ForeignKey(
        CachedSubdivision, on_delete=models.CASCADE, related_name="aliases"
    )
    alias_text = models.TextField()
    normalized_alias = models.TextField(db_index=True)
    embedding = models.JSONField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cached Subdivision Alias"
        verbose_name_plural = "Cached Subdivision Aliases"
        constraints = [
            models.UniqueConstraint(
                fields=["subdivision", "normalized_alias"],
                name="uniq_cached_subdivision_alias",
            )
        ]

    def __str__(self) -> str:
        return self.alias_text
