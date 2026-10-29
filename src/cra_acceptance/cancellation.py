"""Observe actual worker PIDs after pause, SIGTERM and supervisor SIGKILL."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from cra_engine.common import load, save
from cra_engine.store import Store
from .fixtures import prepare


def alive(pid):
    status = subprocess.run(["ps","-o","stat=","-p",str(pid)],capture_output=True,text=True)
    return status.returncode == 0 and status.stdout.strip() and not status.stdout.strip().startswith("Z")


def run(root):
    root = Path(root)
    cases=[]
    for action in ("pause", "terminate", "supervisor-kill"):
        project=prepare(root/action)
        process=subprocess.Popen([sys.executable,"-m","cra_acceptance.faults","--worker-child",str(project)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        pid=None; observed={}
        try:
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                files=list((project/".cra/runs").glob("*/worker-identity.json"))
                if files:
                    pid=load(files[0])["pid"];break
                if process.poll() is not None:break
                time.sleep(.005)
            observed["worker_observed_running"]=bool(pid and alive(pid))
            if action != "supervisor-kill" and pid and alive(pid):
                # Hold the real worker to make cancellation deterministic, without
                # replacing the executor or injecting a fake long-running recipe.
                os.kill(pid,signal.SIGSTOP)
            if action=="pause":
                store=Store(project)
                with store.tx():store.set_meta("paused",True)
                store.close()
            elif process.poll() is None:
                process.send_signal(signal.SIGTERM if action=="terminate" else signal.SIGKILL)
            try:process.communicate(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.communicate()
            deadline=time.monotonic()+3
            while pid and alive(pid) and time.monotonic()<deadline:time.sleep(.05)
            observed["worker_no_longer_executing"]=bool(pid and not alive(pid))
            observed["supervisor_exited"]=process.poll() is not None
            observed["expected_exit"]=process.returncode==(-signal.SIGKILL if action=="supervisor-kill" else 130)
        finally:
            if process.poll() is None:process.kill();process.wait()
            if pid and alive(pid):os.kill(pid,signal.SIGKILL)
        save(root/(action+".json"),{"scenario":action,"checks":observed,"worker_pid":pid,"supervisor_returncode":process.returncode,"scope":"Actual OS-isolated worker lifecycle; SIGSTOP used only by external test controller"})
        cases.append({"id":"worker-"+action,"status":"passed" if all(observed.values()) else "failed","artifacts":["cancellation/"+action+".json"]})
    return cases
