import uuid

from django.db import models


class EventTypeClassifier(models.Model):
    event_type_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.TextField()
    event_pattern = models.TextField()
    article_of_law = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Event type classifier"
        verbose_name_plural = "Event type classifiers"

    def __str__(self) -> str:
        return f"{self.event_type} / {self.article_of_law}"
