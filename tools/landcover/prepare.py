"""Provision frozen model assets and verify the existing inference environment."""

import json
from pathlib import Path
import sys

# ==================== CONFIGURATION ====================
REPOSITORY = Path(__file__).resolve().parents[2]
RELEASE_CONFIG = REPOSITORY / "config/release.local.toml"
OUTPUT = REPOSITORY / ".runtime/landcover-implementation-20261114"
PACKAGE = "/root/autodl-tmp/landcover_inference_handoff_20261114.zip"
ASSETS = "/root/autodl-tmp/landcover-assets-20261114"
INTERPRETER = "/opt/miniforge3/envs/workspace/bin/python"
GPU_INDEX = 5
# =======================================================
sys.path.insert(0, str(REPOSITORY))
from tools.release.config import load  # noqa: E402
from tools.release.executor import Executor  # noqa: E402

if __name__ == "__main__":
    config = load(RELEASE_CONFIG, executing=True)
    payload = {
        "package": PACKAGE,
        "assets": ASSETS,
        "interpreter": INTERPRETER,
        "gpuIndex": GPU_INDEX,
        "networkSource": (
            REPOSITORY / "examples/compute/landcover-unet/core/networks/UNet.py"
        ).read_text(),
    }
    raw = Executor(config, execute=True).ssh(
        [
            config["server"]["python"],
            "-c",
            (Path(__file__).with_name("remote_prepare.py")).read_text(),
        ],
        payload=json.dumps(payload).encode(),
    )
    value = json.loads(raw.decode())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "runtime-compatibility.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2)
    )
    print(json.dumps(value, ensure_ascii=False))
