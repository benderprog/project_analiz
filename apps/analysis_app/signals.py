from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.analysis_app.subdivision_cache import upsert_subdivision_cache
from apps.portaldb.models import Subdivision


@receiver(post_save, sender=Subdivision)
def sync_subdivision_cache_on_save(
    sender, instance: Subdivision, **kwargs
) -> None:
    using = kwargs.get("using")
    if using != "portal":
        return
    upsert_subdivision_cache(instance, rebuild_embeddings=False)
