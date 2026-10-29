#!/usr/bin/env python3
"""Start the local GUI; setup is explicit and never accepts research decisions."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import webbrowser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate the runtime without opening or starting the app")
    parser.add_argument("--python", help="Explicit existing Python runtime, useful for deployment verification")
    parser.add_argument("--no-browser", action="store_true", help="Start the service without opening a browser")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidates = [args.python] if args.python else [str(root / ".cra-runtime/bin/python"), str(root / ".venv/bin/python"), str(root / "work/ui-env/bin/python"), shutil.which("python3.12")]
    executable = None
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            path = str(Path(candidate).absolute())
            if subprocess.run([path, "-c", "import sys; sys.exit(sys.version_info[:2] != (3,12))"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                executable = path
                break
    if executable is None:
        print("请先安装Python 3.12，再双击本文件；没有修改系统环境。")
        return 2
    env = dict(os.environ, PYTHONPATH=str(root / "src"), CRA_DEPLOYMENT="local", CRA_WORKSPACE_ROOT=str(root / ".cra-workspaces"))
    ready = subprocess.run([executable, "-c", "import streamlit,pyreadstat,numpy,pandas,scipy,statsmodels,docx,pypdf,bibtexparser"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not ready:
        if args.check:
            print("运行依赖未就绪；未安装、启动服务或调用模型。")
            return 2
        print("首次启动需要在本项目.cra-runtime中安装声明的Python依赖。不会修改系统Python、现有.venv或模型密钥。")
        if not sys.stdin.isatty() or input("如同意下载并安装，输入 INSTALL；其他输入退出：").strip() != "INSTALL": return 2
        runtime = root / ".cra-runtime/bin/python"
        if not runtime.exists(): subprocess.run([executable, "-m", "venv", str(root / ".cra-runtime")], check=True)
        executable = str(runtime)
        subprocess.run([executable, "-m", "pip", "install", "-e", str(root) + "[engine,ui]"], check=True)
    if args.check:
        print("本机工作台运行环境可用；未启动服务、未创建批准、未调用模型。")
        return 0
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = "http://127.0.0.1:" + str(port)
    process = subprocess.Popen([executable, "-m", "streamlit", "run", str(root / "streamlit_app.py"), "--server.address", "127.0.0.1", "--server.port", str(port), "--server.headless", "true"], cwd=root, env=env)
    try:
        import time
        for _ in range(100):
            if process.poll() is not None: return process.returncode
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1): break
            except OSError: time.sleep(.1)
        else: raise RuntimeError("本机服务未能就绪；没有打开空白页面")
        print("研究工作台已在本机启动：" + url)
        print("关闭此终端会结束服务。请定期下载私有恢复备份；密钥在页面填写。")
        if not args.no_browser: webbrowser.open(url)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    try: raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError):
        print("本机服务未完成启动。请检查Python、依赖和端口；不会回显材料或密钥。")
        raise SystemExit(2)
