"""Audited worker entry; no model code, credentials, control-state access or network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cra_engine.common import EngineError, load, save


def network_denied(host_listener_port=None):
    import socket
    denied = False
    try:
        connection = socket.socket()
        connection.settimeout(0.2)
        connection.connect(("127.0.0.1", host_listener_port or 9))
    except PermissionError:
        denied = True
    except OSError as exc:
        denied = exc.errno in (1, 13, 101)
        if host_listener_port is not None:
            # A live host listener cannot be refused from the host namespace.
            # Linux's new network namespace has its own empty loopback stack.
            import errno
            denied = denied or exc.errno == errno.ECONNREFUSED or isinstance(exc, TimeoutError)
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    return denied


def probe(directory, host_listener_port=None):
    if host_listener_port is not None:
        from cra_engine.common import require
        require(type(host_listener_port) is int and 0 < host_listener_port < 65536, "Invalid host control listener")
    denied = network_denied(host_listener_port)
    control = directory.parents[1] / "state.sqlite"
    read_denied = False
    try:
        control.read_bytes()
    except (PermissionError, FileNotFoundError):
        read_denied = True
    write_denied = False
    try:
        (directory.parents[2] / "isolation-escape-test").write_text("not allowed")
    except (PermissionError, OSError):
        write_denied = True
    return {"network_denied": denied, "write_denied": write_denied, "control_read_denied": read_denied}


def main():
    import os
    if sys.platform == "darwin" and os.environ.get("CRA_SUPERVISOR_PID"):
        import threading, time
        supervisor = int(os.environ["CRA_SUPERVISOR_PID"])
        def watch_parent():
            while True:
                if os.getppid() != supervisor:
                    os._exit(125)
                time.sleep(0.1)
        threading.Thread(target=watch_parent, daemon=True).start()
    source, target = map(Path, sys.argv[1:3])
    try:
        request = load(source)
        action, args = request["action"], request["payload"]
        if action == "probe":
            result = probe(target.parent, args.get("host_listener_port"))
        elif action == "audit":
            from cra_engine.statistics import audit
            result = audit(**args)
        elif action == "analysis":
            from cra_engine.statistics import fit_models
            # The trusted worker sets this path, never the model or protocol.
            args["progress_path"] = str(target.parent / "specification-progress.json")
            result = fit_models(**args)
        else:
            raise EngineError("Unknown trusted recipe")
        save(target, {"ok": True, "result": result})
    except Exception as exc:
        if 'action' in locals() and action == "probe":
            import traceback
            (target.parent / "probe-error.txt").write_text(traceback.format_exc())
        save(target, {"ok": False, "error": str(exc) if isinstance(exc, EngineError) else "Local recipe failed; no raw values transmitted"})


if __name__ == "__main__":
    main()
