"""Bind verified GPU assets and interpreter in the existing server TOML."""

import json
from pathlib import Path
import sys

# ==================== CONFIGURATION ====================
ROOT = Path(__file__).resolve().parents[2]
RELEASE_CONFIG = ROOT / "config/release.local.toml"
EVIDENCE = (
    ROOT / ".runtime/landcover-implementation-20261114/runtime-compatibility.json"
)
ASSET_ROOT = "/root/autodl-tmp/landcover-assets-20261114"
LEASE_ROOT = "/root/autodl-tmp/geomanager-gpu-leases"
INTERPRETER = "/opt/miniforge3/envs/workspace/bin/python"
GPU_IDS = [5, 6, 7]
PROJECT_IDS = [2]
# =======================================================
sys.path.insert(0, str(ROOT))
from tools.release.config import load  # noqa: E402
from tools.release.executor import Executor  # noqa: E402

if __name__ == "__main__":
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["ready"] and len(evidence["models"]) == 5
    config = load(RELEASE_CONFIG, executing=True)
    profile = {
        "enabled": True,
        "interpreter": INTERPRETER,
        "asset_root": ASSET_ROOT,
        "lease_root": LEASE_ROOT,
        "proj_data": evidence["projData"],
        "gdal_data": evidence["gdalData"],
        "gpu_ids": GPU_IDS,
        "project_ids": PROJECT_IDS,
        "allowed_algorithms": ["landcover-unet-infer"],
        "memory_mb": 16384,
        "timeout_seconds": 1800,
        "max_band_pixels": 150000000,
        "busy_memory_mb": 1024,
    }
    source = """
import json,os,sys,tomllib
from pathlib import Path
spec=json.load(sys.stdin);path=Path(spec['config']);assert path.is_file() and not path.is_symlink()
text=path.read_text();value=tomllib.loads(text);existing=value.get('compute',{}).get('gpu')
if existing is None:
 rows=['','[compute.gpu]']
 for key,value in spec['profile'].items():rows.append(key+' = '+json.dumps(value))
 updated=text+'\\n'.join(rows)+'\\n';assert tomllib.loads(updated)['compute']['gpu']==spec['profile']
 temporary=path.with_name(path.name+'.landcover-tmp');temporary.write_text(updated);temporary.chmod(path.stat().st_mode&0o777);os.replace(temporary,path)
else:assert existing==spec['profile'],'Existing GPU configuration differs; preserve it for review'
Path(spec['profile']['lease_root']).mkdir(parents=True,exist_ok=True)
print(json.dumps({'configured':True,'runtime':'python-geospatial-gpu-v1','projects':spec['profile']['project_ids'],'gpuIds':spec['profile']['gpu_ids']}))
"""
    result = Executor(config, execute=True).ssh(
        [config["server"]["python"], "-c", source],
        payload=json.dumps(
            {"config": config["server"]["productionConfig"], "profile": profile}
        ).encode(),
    )
    output = json.loads(result.decode())
    EVIDENCE.with_name("gpu-configuration.json").write_text(
        json.dumps(output, indent=2)
    )
    print(json.dumps(output))
