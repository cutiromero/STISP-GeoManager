"""Standalone Linux confinement for model-written data preparation scripts.

The trusted parent owns task state and validates artifacts. This child receives
only authorized independent input copies and one writable working directory.
It never imports Django, an algorithm package, or platform configuration.
"""

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import traceback

# ==================== CONFIGURATION ====================
POLICY_VERSION = 1
MINIMUM_LANDLOCK_ABI = 3
MAX_CODE_CHARACTERS = 16000
MEMORY_BYTES = 2 * 1024**3
MAX_FILE_BYTES = 256 * 1024**2
CPU_SECONDS = 60
LIBRARIES = ("numpy", "pandas", "geopandas", "rasterio", "pyogrio", "pyproj", "shapely")
# x86_64 allowlist: ordinary file/memory/math/time operations. Namespace,
# process execution/foreign signalling, network, ptrace, privileged IPC,
# io_uring, capability and credential changes are absent, including future calls.
ALLOWED_SYSCALLS = frozenset(
    {
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        32,
        33,
        35,
        36,
        37,
        38,
        39,
        40,
        60,
        61,
        63,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        86,
        87,
        88,
        89,
        90,
        91,
        95,
        96,
        97,
        98,
        99,
        100,
        102,
        104,
        107,
        108,
        110,
        111,
        137,
        138,
        158,
        186,
        202,
        204,
        217,
        218,
        219,
        228,
        229,
        230,
        231,
        257,
        258,
        262,
        263,
        264,
        265,
        266,
        267,
        268,
        269,
        270,
        271,
        273,
        281,
        289,
        290,
        292,
        293,
        309,
        318,
        332,
        334,
        436,
        439,
    }
)
# =======================================================


class IsolationUnavailable(RuntimeError):
    pass


def probe():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        return {
            "available": False,
            "policyVersion": POLICY_VERSION,
            "reason": "受限脚本需要Linux x86_64内核隔离",
        }
    if os.geteuid() != 0:
        return {
            "available": False,
            "policyVersion": POLICY_VERSION,
            "reason": "当前服务未配置独立脚本执行身份",
        }
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    return {
        "available": abi >= MINIMUM_LANDLOCK_ABI,
        "policyVersion": POLICY_VERSION,
        "landlockAbi": max(0, abi),
        "reason": "" if abi >= MINIMUM_LANDLOCK_ABI else "内核文件隔离不可用",
    }


def checked(result, operation):
    if result < 0:
        raise IsolationUnavailable(operation + ": " + os.strerror(ctypes.get_errno()))
    return result


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def restrict_filesystem(read_paths, writable):
    evidence = probe()
    if not evidence["available"]:
        raise IsolationUnavailable(evidence["reason"])
    libc = ctypes.CDLL(None, use_errno=True)
    handled = (1 << 15) - 1
    if evidence["landlockAbi"] >= 5:
        handled |= 1 << 15  # ioctl on devices is denied too.
    attr = Ruleset(handled)
    ruleset = checked(
        libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0),
        "create filesystem rules",
    )
    read_file, read_dir, execute = 1 << 2, 1 << 3, 1
    writable_rights = handled & ~sum(1 << bit for bit in (0, 6, 9, 10, 11, 15))
    try:
        paths = {
            str(Path(path).resolve()): False
            for path in read_paths
            if Path(path).exists()
        }
        paths[str(Path(writable).resolve())] = True
        for path, write in sorted(paths.items()):
            is_dir = Path(path).is_dir()
            access = (
                writable_rights
                if write
                else read_file | (read_dir | execute if is_dir else 0)
            )
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, fd)
                checked(
                    libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0),
                    "add filesystem rule",
                )
            finally:
                os.close(fd)
        checked(libc.prctl(38, 1, 0, 0, 0), "no new privileges")
        checked(libc.syscall(446, ruleset, 0), "restrict filesystem")
    finally:
        os.close(ruleset)


class Filter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]


def restrict_syscalls():
    # A different ABI is killed. The x32 syscall range is not in the allowlist.
    instructions = [
        Filter(0x20, 0, 0, 4),
        Filter(0x15, 1, 0, 0xC000003E),
        Filter(0x06, 0, 0, 0x80000000),
        Filter(0x20, 0, 0, 0),
    ]
    allow, deny = 0x7FFF0000, 0x00050000 | errno.EPERM

    def special(number, body):
        instructions.append(Filter(0x15, 0, len(body), number))
        instructions.extend(body)

    # New threads inherit both restrictions; new processes are forbidden. Make
    # clone3 fall back to the inspectable clone flags. The non-root UID below
    # makes RLIMIT_NPROC effective for this job's threads.
    special(435, [Filter(0x06, 0, 0, 0x00050000 | errno.ENOSYS)])
    special(
        56,
        [
            Filter(0x20, 0, 0, 16),
            Filter(0x54, 0, 0, 0x10900),
            Filter(0x15, 0, 1, 0x10900),
            Filter(0x06, 0, 0, allow),
            Filter(0x06, 0, 0, deny),
        ],
    )
    # libc getrlimit uses prlimit64(0, resource, NULL, old). Never permit a
    # different process or any new limit pointer after confinement.
    special(
        302,
        [
            Filter(0x20, 0, 0, 16),
            Filter(0x15, 0, 5, 0),
            Filter(0x20, 0, 0, 32),
            Filter(0x15, 0, 3, 0),
            Filter(0x20, 0, 0, 36),
            Filter(0x15, 0, 1, 0),
            Filter(0x06, 0, 0, allow),
            Filter(0x06, 0, 0, deny),
        ],
    )
    for number in (62, 234):
        special(
            number,
            [
                Filter(0x20, 0, 0, 16),
                Filter(0x15, 0, 1, os.getpid()),
                Filter(0x06, 0, 0, allow),
                Filter(0x06, 0, 0, deny),
            ],
        )
    for number in sorted(ALLOWED_SYSCALLS):
        instructions.extend(
            [Filter(0x15, 0, 1, number), Filter(0x06, 0, 0, 0x7FFF0000)]
        )
    instructions.append(Filter(0x06, 0, 0, 0x00050000 | errno.EPERM))
    array = (Filter * len(instructions))(*instructions)
    program = Program(len(array), array)
    libc = ctypes.CDLL(None, use_errno=True)
    checked(libc.prctl(38, 1, 0, 0, 0), "no new privileges")
    result = libc.syscall(317, 1, 1, ctypes.byref(program))  # TSYNC
    if result != 0:
        raise IsolationUnavailable("无法同步安装系统调用隔离")


def drop_privileges(working):
    libc = ctypes.CDLL(None, use_errno=True)

    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]

    class Data(ctypes.Structure):
        _fields_ = [
            ("effective", ctypes.c_uint32),
            ("permitted", ctypes.c_uint32),
            ("inheritable", ctypes.c_uint32),
        ]

    header, original = Header(0x20080522, 0), (Data * 2)()
    checked(
        libc.capget(ctypes.byref(header), ctypes.byref(original)), "read capabilities"
    )
    keep = 0
    if os.geteuid() == 0:
        # Runtime libraries live below /root on this deployment. Retain only
        # read traversal (or DAC override when the container lacks READ_SEARCH),
        # still confined by Landlock. FOWNER/CHOWN and every process/network
        # privilege are removed. Registered files remain owned by another UID.
        capability = 2 if original[0].permitted & (1 << 2) else 1
        keep = 1 << capability
        if not original[0].permitted & keep:
            raise IsolationUnavailable("无法为独立脚本提供受控的运行库读取")
        uid = 1_000_000 + os.getpid()
        os.chown(working, uid, uid)
        os.chmod(working, 0o700)
        checked(libc.prctl(8, 1, 0, 0, 0), "keep read traversal during UID change")
        for number in range(64):
            if libc.prctl(23, number, 0, 0, 0) > 0 and not keep & (1 << number):
                checked(libc.prctl(24, number, 0, 0, 0), "drop capability bounding set")
        parent = os.getppid()
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
        checked(libc.prctl(1, 9, 0, 0, 0), "parent death boundary")
        if os.getppid() != parent:
            os._exit(1)
    data = (Data * 2)()
    data[0].effective = data[0].permitted = keep
    checked(libc.capset(ctypes.byref(header), ctypes.byref(data)), "drop capabilities")


def runtime_paths():
    result = set()
    from pyproj.datadir import get_data_dir
    from rasterio._env import GDALDataFinder

    for path in (get_data_dir(), GDALDataFinder().search()):
        if path:
            result.add(path)
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        result.add(sysconfig.get_path(key))
    for path in (
        "/lib",
        "/lib64",
        "/usr/lib",
        "/usr/lib64",
        "/usr/share/proj",
        "/usr/share/gdal",
        "/usr/share/zoneinfo",
        "/etc/ld.so.cache",
        "/etc/localtime",
        "/dev/urandom",
    ):
        if Path(path).exists():
            result.add(path)
    for key in ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA", "GDAL_DRIVER_PATH"):
        if os.environ.get(key):
            result.add(os.environ[key])
    # Only already-loaded binary libraries, not the process's application root.
    for line in Path("/proc/self/maps").read_text().splitlines():
        pieces = line.split(maxsplit=5)
        if len(pieces) == 6 and pieces[5].startswith("/") and Path(pieces[5]).is_file():
            result.add(pieces[5])
    return result


class Context:
    def __init__(self, value):
        self._inputs = {key: Path(path) for key, path in value["inputs"].items()}
        self._output = Path(value["workingDirectory"])
        self._filename = value["filename"]
        self.parameters = value.get("contract", {})

    def input_path(self, key):
        return self._inputs[key]

    def output_path(self, filename):
        if filename != self._filename:
            raise ValueError("脚本只能生成本次声明的目标文件")
        return self._output / filename


def main():
    if not probe()["available"]:
        raise IsolationUnavailable(probe()["reason"])
    import resource

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    code = request["code"]
    if not isinstance(code, str) or not 1 <= len(code) <= MAX_CODE_CHARACTERS:
        raise ValueError("适配脚本长度无效")
    for key in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "GDAL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "ARROW_NUM_THREADS",
    ):
        os.environ[key] = "1"
    os.environ["ARROW_DEFAULT_MEMORY_POOL"] = "system"
    os.environ["MALLOC_CONF"] = "background_thread:false"
    import importlib

    for library in LIBRARIES:
        importlib.import_module(library)
    from rasterio.warp import reproject  # noqa: F401
    from rasterio.features import rasterize  # noqa: F401

    if len(os.listdir("/proc/self/task")) != 1:
        # Some binary wheels create a background allocator thread during import.
        # Only the fresh fork executes user code; the trusted parent only waits.
        # The child dies with that parent, including on platform cancellation.
        import warnings

        parent = os.getpid()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            child = os.fork()
        if child:
            _, status = os.waitpid(child, 0)
            result = os.waitstatus_to_exitcode(status)
            os._exit(result if result >= 0 else 128 - result)
        libc = ctypes.CDLL(None, use_errno=True)
        checked(libc.prctl(1, 9, 0, 0, 0), "parent death boundary")
        if os.getppid() != parent:
            os._exit(1)
    context = Context(request)
    working = Path(request["workingDirectory"]).resolve()
    assert working.is_dir() and all(path.is_file() for path in context._inputs.values())
    read_paths = runtime_paths() | {
        str(path.resolve()) for path in context._inputs.values()
    }
    os.chdir(working)
    for item, maximum in [
        (resource.RLIMIT_CPU, CPU_SECONDS),
        (resource.RLIMIT_AS, MEMORY_BYTES),
        (resource.RLIMIT_FSIZE, MAX_FILE_BYTES),
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_NOFILE, 128),
        (resource.RLIMIT_NPROC, 32),
    ]:
        soft, hard = resource.getrlimit(item)
        chosen = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        resource.setrlimit(item, (chosen, chosen))
    task_fd = os.open("/proc/self/task", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        if len(os.listdir(task_fd)) != 1:
            raise IsolationUnavailable("脚本隔离需要独立单线程子进程")
        restrict_filesystem(read_paths, working)
        drop_privileges(working)
        restrict_syscalls()
        if len(os.listdir(task_fd)) != 1:
            raise IsolationUnavailable("脚本隔离前存在额外线程")
    finally:
        os.close(task_fd)
    namespace = {"__name__": "data_preparation_script", "context": context}
    exec(compile(code, "<data-preparation-script>", "exec"), namespace)
    if not callable(namespace.get("run")):
        raise ValueError("适配脚本需要定义run(context)")
    namespace["run"](context)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        frames = traceback.extract_tb(error.__traceback__)
        line = next(
            (
                frame.lineno
                for frame in reversed(frames)
                if frame.filename == "<data-preparation-script>"
            ),
            None,
        )
        # Bounded exception detail helps the agent repair actual conversion
        # failures. No Django configuration or platform files are in this child.
        print(
            json.dumps(
                {
                    "errorType": type(error).__name__,
                    "message": str(error)[:600],
                    "line": line,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
