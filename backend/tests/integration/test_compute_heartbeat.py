from apps.compute.models import RuntimeLease
from apps.compute.worker import pulse


def test_heartbeat_preserves_runtime_state_between_queue_ticks():
    RuntimeLease.objects.filter(name="worker").delete()
    pulse({"ready": True, "id": "python-geospatial-native-v1"})
    first = RuntimeLease.objects.get(name="worker")
    pulse()
    current = RuntimeLease.objects.get(name="worker")
    assert current.heartbeat >= first.heartbeat
    assert current.detail == first.detail
    pulse({"ready": False, "detail": "missing dependency"})
    current.refresh_from_db()
    assert current.detail == {"ready": False, "detail": "missing dependency"}
