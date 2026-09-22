from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser

from apps.core.permissions import has_feature_perm


def can_manage_raster_data(user: AbstractBaseUser) -> bool:
    return has_feature_perm(user, "raster.manage_raster_dataset") or has_feature_perm(
        user, "catalog.change_dataresource"
    )
