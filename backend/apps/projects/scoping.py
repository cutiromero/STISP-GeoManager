from django.core.exceptions import ValidationError
from django.db import models

from .context import current_scope, selected_project_id


class ScopedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if "project_tag" in kwargs or "project_tag_id" in kwargs:
            raise ValidationError("项目归属不可通过普通更新修改")
        for key in kwargs:
            field_name = key.removesuffix("_id")
            try:
                field = self.model._meta.get_field(field_name)
            except Exception:
                continue
            if field.is_relation and hasattr(field.related_model, "project_tag"):
                # Validate each row before a relation-changing bulk update.
                for item in self.only("pk", "project_tag_id"):
                    setattr(item, key, kwargs[key])
                    item.validate_project_relations()
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        for obj in objs:
            obj.prepare_project_scope()
            obj.validate_project_relations()
        return super().bulk_create(objs, **kwargs)


class ProjectManager(models.Manager.from_queryset(ScopedQuerySet)):
    def get_queryset(self):
        query = super().get_queryset()
        scope = current_scope.get()
        if scope is not None:
            query = query.filter(project_tag_id__in=scope.ids)
        return query


class ProjectScopedModel(models.Model):
    project_tag = models.ForeignKey(
        "projects.Project",
        default=1,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="项目标签",
    )
    objects = ProjectManager()

    class Meta:
        abstract = True

    def prepare_project_scope(self):
        scope = current_scope.get()
        if scope is None:
            return
        if self._state.adding and self.project_tag_id == 1:
            self.project_tag_id = (
                1
                if self._meta.app_label == "audit" and scope.selected is None
                else selected_project_id()
            )
        if self.project_tag_id not in scope.ids:
            raise ValidationError("对象不属于当前项目")
        if not self._state.adding:
            old = (
                type(self)
                ._base_manager.filter(pk=self.pk)
                .values_list("project_tag_id", flat=True)
                .first()
            )
            if old is not None and old != self.project_tag_id:
                raise ValidationError("项目归属不可通过普通更新修改")

    def validate_project_relations(self):
        from .snapshots import validate_snapshot_project

        for name in ("snapshot", "workspace_snapshot", "source_workspace_snapshot"):
            if hasattr(self, name):
                validate_snapshot_project(getattr(self, name))
        for field in self._meta.concrete_fields:
            if not field.is_relation or field.name == "project_tag":
                continue
            related = field.related_model
            if not hasattr(related, "project_tag"):
                continue
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue
            parent_project = (
                related._base_manager.filter(pk=related_id)
                .values_list("project_tag_id", flat=True)
                .first()
            )
            if parent_project is not None and parent_project != self.project_tag_id:
                raise ValidationError({field.name: "关联对象必须属于同一项目"})

    def save(self, *args, **kwargs):
        self.prepare_project_scope()
        self.validate_project_relations()
        return super().save(*args, **kwargs)


def validate_scoped_m2m(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    if not hasattr(instance, "project_tag_id") or not hasattr(model, "project_tag"):
        return
    if (
        model._base_manager.filter(pk__in=pk_set)
        .exclude(project_tag_id=instance.project_tag_id)
        .exists()
    ):
        raise ValidationError("不能关联其他项目的数据")
