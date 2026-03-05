import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.analysis_app.semantic import get_sentence_model
from apps.analysis_app.subdivision_utils import build_embedding_source_hash, to_py_floats
from apps.analysis_app.utils.text_normalize import normalize_subdivision_text


SVODKA_TEMPLATE_DEFAULT_ANCHOR_MATCH_THRESHOLD = float(
    getattr(settings, "TEMPLATE_ANCHOR_START_MIN_SIM", 0.60)
)


class AnalysisRun(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    file = models.FileField(upload_to="uploads/")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    created_session_key = models.CharField(max_length=40, blank=True, default="", db_index=True)
    detected_pu_id = models.CharField(max_length=64, blank=True, default="")
    detected_pu_name = models.CharField(max_length=255, blank=True, default="")
    selected_pu_id = models.CharField(max_length=64, blank=True, default="")
    selected_pu_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    progress_total = models.PositiveIntegerField(null=True, blank=True, default=None)
    progress_done = models.PositiveIntegerField(null=True, blank=True, default=None)
    progress_updated_at = models.DateTimeField(null=True, blank=True, default=None)
    debug_pipeline = models.JSONField(default=dict, blank=True)
    debug_pipeline_updated_at = models.DateTimeField(null=True, blank=True)
    debug_package_file = models.FileField(upload_to="debug_packages/", null=True, blank=True)
    debug_package_created_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Run {self.run_id}"


class FeatureFlags(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    debug_mode = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Флаги"
        verbose_name_plural = "Флаги"

    @classmethod
    def get_solo(cls):
        return cls.objects.get_or_create(pk=1)[0]

    @classmethod
    def is_application_debug_enabled(cls) -> bool:
        try:
            obj = cls.objects.only("debug_mode").get(pk=1)
            return bool(obj.debug_mode)
        except cls.DoesNotExist:
            return False

    @classmethod
    def is_effective_debug_enabled(cls) -> bool:
        return cls.is_application_debug_enabled()

    @classmethod
    def is_debug_enabled(cls) -> bool:
        return cls.is_effective_debug_enabled()


class SvodkaTemplate(models.Model):
    class Scope(models.TextChoices):
        PU = "pu", "PU"
        GENERAL = "general", "Общая сводка"

    template_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=20, choices=Scope.choices)
    pu_id = models.CharField(max_length=64, blank=True, default="")
    pu_name = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(upload_to="svodka_templates/", blank=True, null=True)
    begin_marker = models.CharField(max_length=32, default="[BEGIN]")
    end_marker = models.CharField(max_length=32, default="[END]")
    anchor_match_threshold = models.FloatField(
        default=SVODKA_TEMPLATE_DEFAULT_ANCHOR_MATCH_THRESHOLD,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Порог совпадения якоря",
        help_text=(
            "Чем ниже — тем проще найти якорь при небольших изменениях, "
            "но выше риск ложных совпадений. Рекомендовано 0.55–0.70."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Шаблон сводки"
        verbose_name_plural = "Шаблоны сводки"
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "pu_id"],
                condition=models.Q(is_active=True),
                name="uniq_active_svodka_template_per_scope_pu",
            )
        ]

    def __str__(self) -> str:
        label = self.pu_name or self.pu_id or "Общая сводка"
        return f"{self.get_scope_display()}: {label}"

    @staticmethod
    def _normalize_label(value: str | None) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def clean(self) -> None:
        super().clean()
        normalized_general = self._normalize_label("Общая сводка")
        normalized_name = self._normalize_label(self.pu_name)

        if not (self.pu_id or "").strip() or normalized_name == normalized_general:
            self.scope = self.Scope.GENERAL
            self.pu_id = ""
            if not (self.pu_name or "").strip():
                self.pu_name = "Общая сводка"

        if self.scope == self.Scope.PU and not (self.pu_id or "").strip():
            self.scope = self.Scope.GENERAL
            self.pu_id = ""
            if not (self.pu_name or "").strip():
                self.pu_name = "Общая сводка"

    def save(self, *args, **kwargs) -> None:
        self.clean()
        if self.scope == self.Scope.GENERAL:
            self.pu_id = ""

        super().save(*args, **kwargs)

        if self.is_active:
            (
                SvodkaTemplate.objects.filter(scope=self.scope, pu_id=self.pu_id, is_active=True)
                .exclude(template_id=self.template_id)
                .update(is_active=False)
            )


class AnalysisParagraph(models.Model):
    class SourceKind(models.TextChoices):
        PARAGRAPH = "paragraph", "Paragraph"
        TABLE_ROW = "table_row", "Table row"

    run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name="paragraphs")
    idx = models.PositiveIntegerField()
    text = models.TextField()
    source_kind = models.CharField(
        max_length=20,
        choices=SourceKind.choices,
        default=SourceKind.PARAGRAPH,
    )
    source_cells = models.JSONField(null=True, blank=True)
    source_table_header_cells = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Paragraph {self.idx}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "idx"], name="uniq_analysis_paragraph_run_idx"),
        ]
        indexes = [
            models.Index(fields=["run", "idx"], name="analysis_paragraph_run_idx_idx"),
        ]


class AnalysisResult(models.Model):
    paragraph = models.OneToOneField(
        AnalysisParagraph, on_delete=models.CASCADE, related_name="result", db_index=True
    )
    extracted_attributes = models.JSONField(default=dict)
    match_result = models.JSONField(default=dict)
    matched = models.BooleanField(default=False)
    title = models.CharField(max_length=255, blank=True, default="")
    preview = models.CharField(max_length=120, blank=True, default="")
    status_timestamp = models.CharField(max_length=16, blank=True, default="neutral")
    status_subdivision = models.CharField(max_length=16, blank=True, default="neutral")
    status_offenders = models.CharField(max_length=16, blank=True, default="neutral")
    status_event_type = models.CharField(max_length=16, blank=True, default="neutral")
    status_article = models.CharField(max_length=16, blank=True, default="neutral")
    detail_payload_cache = models.JSONField(default=dict, blank=True)
    detail_payload_cached_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Result for {self.paragraph_id}"

    class Meta:
        indexes = [
            models.Index(fields=["paragraph"], name="analysis_result_paragraph_idx"),
        ]


class CachedPU(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal_pu_id = models.UUIDField(unique=True, db_index=True)
    short_name = models.CharField(max_length=255)
    full_name = models.CharField(max_length=255)
    normalized_short_name = models.TextField(blank=True, default="")
    normalized_full_name = models.TextField(blank=True, default="")
    embedding_short = models.JSONField(blank=True, null=True)
    embedding_full = models.JSONField(blank=True, null=True)
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
    parent_pu_id = models.UUIDField(null=True, blank=True)
    normalized_short_name = models.TextField(blank=True, default="")
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
        if not self.normalized_name and self.name:
            self.normalized_name = normalize_subdivision_text(self.name)
        if normalized_source is None:
            normalized_source = (
                self.normalized_short_name or self.normalized_name or ""
            )

        new_hash = build_embedding_source_hash(normalized_source, self.legacy_aliases)
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
                embedding = model.encode([normalized_source])[0]
                self.embedding = to_py_floats(embedding)
                self.embedding_updated_at = timezone.now()

        if update_fields is not None:
            update_fields = set(update_fields)
            update_fields.update(
                {"normalized_name", "normalized_short_name", "embedding_source_hash", "updated_at"}
            )
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


class PortalDbConnectionSettings(models.Model):
    class Profile(models.TextChoices):
        TEST = "TEST", "Тестовая"
        PROD = "PROD", "Боевая"

    profile = models.CharField(max_length=10, choices=Profile.choices, default=Profile.TEST)
    host = models.CharField(max_length=255, blank=True, default="")
    port = models.PositiveIntegerField(default=5432)
    db_name = models.CharField(max_length=255, blank=True, default="")
    user = models.CharField(max_length=255, blank=True, default="")
    password_encrypted = models.TextField(blank=True, default="")
    last_check_ok = models.BooleanField(null=True, default=None)
    last_check_error = models.TextField(blank=True, default="")
    last_check_at = models.DateTimeField(null=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройка подключения к базе данных"
        verbose_name_plural = "Настройка подключения к базе данных"

    def __str__(self) -> str:
        return f"{self.get_profile_display()}: {self.host}:{self.port}/{self.db_name}"
