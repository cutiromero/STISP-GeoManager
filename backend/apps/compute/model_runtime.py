"""Common dispatch for configured model runtimes; execution remains in compute."""

RUNTIMES = {"python-geospatial-gpu-v1", "python-geospatial-ml-v1"}


def implementation(manifest):
    from . import gpu_runtime, ml_runtime

    return ml_runtime if manifest.get("runtime") == ml_runtime.RUNTIME else gpu_runtime


def configured(manifest, project_id=None):
    return implementation(manifest).configured(manifest, project_id)


def binding(manifest, project_id=None):
    return implementation(manifest).binding(manifest, project_id)


def inspect(manifest, project_id=None):
    return implementation(manifest).inspect(manifest, project_id)


def require_binding(task):
    return implementation(task.version.manifest).require_binding(task)


def lease(profile):
    from . import gpu_runtime, ml_runtime

    return (
        ml_runtime if isinstance(profile, ml_runtime.MLProfile) else gpu_runtime
    ).lease(profile)
