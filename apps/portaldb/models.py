import uuid

from django.db import models


class Pu(models.Model):
    pu_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=255)

    class Meta:
        db_table = "pu"
        verbose_name = "PU"
        verbose_name_plural = "PUs"

    def __str__(self) -> str:
        return self.short_name or self.full_name


class Subdivision(models.Model):
    subdivision_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=255, db_index=True, blank=True, default="")
    parent_pu = models.ForeignKey(Pu, on_delete=models.CASCADE)

    class Meta:
        db_table = "subdivision"
        verbose_name = "Subdivision"
        verbose_name_plural = "Subdivisions"

    def display_label(self) -> str:
        parent_pu = getattr(self, "parent_pu", None)
        pu_label = ""
        if parent_pu:
            pu_label = parent_pu.short_name or parent_pu.full_name
        return f"{self.name} {pu_label}".strip()

    def __str__(self) -> str:
        return self.display_label()


class Event(models.Model):
    event_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date_detection = models.DateTimeField()
    find_subdivision_unit = models.ForeignKey(Subdivision, on_delete=models.CASCADE)
    event_type = models.TextField()
    article_of_law = models.CharField(max_length=255)

    class Meta:
        db_table = "event"
        verbose_name = "Event"
        verbose_name_plural = "Events"

    def __str__(self) -> str:
        return f"{self.event_type} ({self.date_detection})"


class Offender(models.Model):
    offender_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=255)
    second_name = models.CharField(max_length=255)
    patronymic_name = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField()
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="offenders")

    class Meta:
        db_table = "offenders"
        verbose_name = "Offender"
        verbose_name_plural = "Offenders"

    def __str__(self) -> str:
        return f"{self.second_name} {self.first_name}"
