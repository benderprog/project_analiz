from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.analysis_app.pu_cache import upsert_pu_cache
from apps.analysis_app.subdivision_cache import upsert_subdivision_cache
from apps.portaldb.models import Pu, Subdivision


@receiver(post_save, sender=Subdivision)
def sync_subdivision_cache_on_save(
    sender, instance: Subdivision, **kwargs
) -> None:
    using = kwargs.get("using")
    if using != "portal":
        return
    upsert_subdivision_cache(instance, rebuild_embeddings=False)


@receiver(post_save, sender=Pu)
def sync_pu_cache_on_save(sender, instance: Pu, **kwargs) -> None:
    using = kwargs.get("using")
    if using != "portal":
        return
    upsert_pu_cache(instance, rebuild_embeddings=False)
