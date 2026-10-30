"""Streamlit Community Cloud entrypoint. No credentials or research data bundled."""
from pathlib import Path
import sys

# Community Cloud can reuse installed project wheels when requirements don't
# change. The deployed, version-controlled checkout is the UI/runtime authority;
# installed extras provide dependencies. No user-supplied path is accepted.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cra_workspace.app import main

main()
