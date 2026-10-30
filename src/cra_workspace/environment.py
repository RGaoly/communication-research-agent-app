"""Non-billing host diagnostics, independent of any researcher's materials."""
import ctypes
import ctypes.util
import errno
from pathlib import Path
import platform
import tempfile

from cra_engine import __version__
from cra_engine.common import EngineError, digest, now, sha, source_fingerprint
from cra_engine.execution import doctor
from cra_engine.statistics import recipe_identity
from cra_engine.store import Store, initialize


def inspect_environment(store):
    report = {"at": now(), "engine_version": __version__, "recipe": digest(recipe_identity()),
              "engine_source_sha256": source_fingerprint(),
              "workspace_source_sha256": digest({p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))}),
              "platform": {"system": platform.system(), "kernel": platform.release(), "machine": platform.machine()}}
    if platform.system() == "Linux":
        report["platform"]["libseccomp_available"] = bool(ctypes.util.find_library("seccomp"))
        if platform.machine() in ("x86_64", "aarch64", "riscv64"):
            libc = ctypes.CDLL(None, use_errno=True)
            libc.syscall.restype = ctypes.c_long
            # Read-only Landlock ABI query; never changes the host's protection.
            abi = libc.syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
            report["platform"]["landlock_abi"] = abi if abi >= 0 else None
            if abi < 0: report["platform"]["landlock_error"] = errno.errorcode.get(ctypes.get_errno(), "UNKNOWN")
    try:
        result = doctor(store)
        report.update(passed=True, isolation=result["isolation"], controls=result["result"], worker=result.get("worker"))
    except (EngineError, OSError):
        report.update(passed=False, message="当前托管环境未通过真实隔离自检，自动统计不可用；可整理材料并导出私有备份至经验证的本机环境运行。")
    return report


def inspect_host(remote_executor=None):
    """Temporary synthetic control only: no data, key, approval or model request."""
    with tempfile.TemporaryDirectory(prefix="cra-environment-") as folder:
        root = Path(folder).resolve() / "probe"
        initialize(root, "Synthetic host capability probe", synthetic=True)
        store = Store(root)
        try:
            if remote_executor is not None:
                store.remote_executor = remote_executor
                with store.tx(): store.put("brief", "research_brief", {"execution": {"backend": "remote", "endpoint": remote_executor.endpoint}})
            return inspect_environment(store)
        finally: store.close()
