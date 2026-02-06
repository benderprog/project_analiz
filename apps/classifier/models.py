import uuid

from django.db import models


class EventType(models.Model):
    """Normalized event type for classifier imports and matching."""

    event_type_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.TextField(unique=True)

    class Meta:
        verbose_name = "Event type"
        verbose_name_plural = "Event types"

    def save(self, *args, **kwargs) -> None:
        if self.event_type:
            self.event_type = self.event_type.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.event_type


class EventTypePattern(models.Model):
    """Pattern entry tied to a specific event type and optional article."""

    event_type_pattern_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    event_type = models.ForeignKey(
        EventType, on_delete=models.CASCADE, related_name="patterns"
    )
    pattern = models.TextField()
    article_of_law = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Event type pattern"
        verbose_name_plural = "Event type patterns"
        constraints = [
            models.UniqueConstraint(
                fields=["event_type", "pattern"], name="unique_event_type_pattern"
            )
        ]

    def save(self, *args, **kwargs) -> None:
        if self.pattern:
            self.pattern = self.pattern.strip()
        if self.article_of_law:
            self.article_of_law = self.article_of_law.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        article = self.article_of_law or "-"
        return f"{self.event_type} / {self.pattern} / {article}"
