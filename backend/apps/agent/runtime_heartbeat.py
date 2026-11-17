"""Write queue leases without upgrading a stale SQLite read snapshot."""

from django.utils import timezone

from .models import AgentRuntime


def pulse(name, *, detail=None):
    values = {"heartbeat": timezone.now()}
    if detail is not None:
        values["detail"] = detail
    lease = AgentRuntime.objects.filter(name=name)
    # UPDATE must precede any SELECT, including when called in a claim transaction.
    if not lease.update(**values):
        _, created = AgentRuntime.objects.get_or_create(name=name, defaults=values)
        if not created:
            lease.update(**values)
