"""Bind verified RF assets to the existing environment without dependency changes."""

import json
from pathlib import Path
import sys

# CONFIGURATION
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".runtime/spartina-implementation-20261114/runtime-compatibility.json"
RELEASE_CONFIG = ROOT / "config/release.local.toml"
ASSET_ROOT = (
    "/root/autodl-tmp/china-europe/data/incoming/spartina_alterniflora/raw/模型"
)

sys.path.insert(0, str(ROOT))
from tools.release.config import load  # noqa: E402
from tools.release.executor import Executor  # noqa: E402

if __name__ == "__main__":
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence.get("ready") is True, "请先完成模型兼容检查"
    profile = {
        "enabled": True,
        "project_ids": [13],
        "allowed_algorithms": ["spartina-rf-infer"],
        "asset_root": ASSET_ROOT,
        "model_file": "Random_Forest_model.pkl",
        "model_sha256": evidence["modelSha256"],
        "memory_mb": 8192,
        "timeout_seconds": 1800,
        "max_band_pixels": 100000000,
    }
    config = load(RELEASE_CONFIG, executing=True)
    source = """
import json,os,sys,tomllib
from pathlib import Path
import pyproj
payload=json.load(sys.stdin);path=Path(payload['config']);text=path.read_text();value=tomllib.loads(text)
profile=payload['profile'];profile['proj_data']=pyproj.datadir.get_data_dir();profile['gdal_data']=str(Path(sys.prefix)/'share/gdal')
assert Path(profile['gdal_data']).is_dir()
existing=value.get('compute',{}).get('ml')
if existing is None:
 updated=text+'\\n[compute.ml]\\n'+'\\n'.join(key+' = '+json.dumps(value) for key,value in profile.items())+'\\n'
 assert tomllib.loads(updated)['compute']['ml']==profile
 temporary=path.with_suffix('.spartina-tmp');temporary.write_text(updated);temporary.chmod(path.stat().st_mode&0o777);os.replace(temporary,path)
else:assert existing==profile,'Existing model configuration differs; preserve it'
print(json.dumps({'configured':True,'runtime':'python-geospatial-ml-v1','projectIds':profile['project_ids'],'interpreter':sys.executable}))
"""
    raw = Executor(config, execute=True).ssh(
        [config["server"]["python"], "-c", source],
        payload=json.dumps(
            {"config": config["server"]["productionConfig"], "profile": profile}
        ).encode(),
    )
    (EVIDENCE.parent / "runtime-configuration.json").write_bytes(raw)
    print(raw.decode())
