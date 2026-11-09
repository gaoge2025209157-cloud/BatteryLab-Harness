"""Run the repository-local, machine-validated Origin plotting engine."""
from __future__ import annotations

from pathlib import Path
import runpy


LOCAL_ENGINE = Path(__file__).resolve().with_name("origin_plot_engine.py")
if not LOCAL_ENGINE.is_file():
    raise RuntimeError("Repository-local Origin plotting engine is unavailable: {}".format(LOCAL_ENGINE))

# The v2 adapter prepares audited input tables and run manifests. Plot styling,
# graph construction, Origin project generation, and PNG export remain entirely
# in the validated engine bundled with this repository.
runpy.run_path(str(LOCAL_ENGINE), run_name="__main__")
