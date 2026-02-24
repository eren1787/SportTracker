import sys

from django.apps import AppConfig


class TrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracker"

    def ready(self):
        # Django 4.2.x has a BaseContext.__copy__ implementation that breaks on
        # Python 3.14 when admin templates copy RequestContext.
        if sys.version_info < (3, 14):
            return

        from django.template.context import BaseContext

        if getattr(BaseContext, "_py314_copy_patch", False):
            return

        def _base_context_copy(self):
            duplicate = object.__new__(self.__class__)
            duplicate.__dict__ = self.__dict__.copy()
            duplicate.dicts = self.dicts[:]
            return duplicate

        BaseContext.__copy__ = _base_context_copy
        BaseContext._py314_copy_patch = True
