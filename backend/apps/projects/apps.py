from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"
    verbose_name = "项目标签"

    def ready(self):
        from django.db.models.signals import m2m_changed, post_migrate
        from .scoping import validate_scoped_m2m

        m2m_changed.connect(validate_scoped_m2m, dispatch_uid="projects.scope_m2m")
        post_migrate.connect(
            ensure_default_project, sender=self, dispatch_uid="projects.default"
        )


def ensure_default_project(sender, using, **kwargs):
    from .models import Project

    Project.objects.using(using).get_or_create(
        pk=1,
        defaults={
            "name": "公开",
            "code": "default",
            "is_default": True,
            "sort_order": 0,
        },
    )
