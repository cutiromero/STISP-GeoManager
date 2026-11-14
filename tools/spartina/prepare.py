"""Check the delivered RF with the existing native interpreter; install nothing."""

import json
from pathlib import Path
import sys

# CONFIGURATION
ROOT = Path(__file__).resolve().parents[2]
RELEASE_CONFIG = ROOT / "config/release.local.toml"
ASSETS = "/root/autodl-tmp/china-europe/data/incoming/spartina_alterniflora/raw/模型"
OUTPUT = ROOT / ".runtime/spartina-implementation-20261114/runtime-compatibility.json"

sys.path.insert(0, str(ROOT))
from tools.release.config import load  # noqa:E402
from tools.release.executor import Executor  # noqa:E402

if __name__ == "__main__":
    config = load(RELEASE_CONFIG, executing=True)
    source = """
import hashlib,importlib.metadata as m,json,sys,warnings
from pathlib import Path
import joblib,numpy as np
spec=json.load(sys.stdin);path=Path(spec['assets'])/'Random_Forest_model.pkl'
with warnings.catch_warnings(record=True) as observed:
 warnings.simplefilter('always');model=joblib.load(path);model.n_jobs=1
 values=np.zeros((3,48),dtype='float32');prediction=model.predict(values);probability=model.predict_proba(values)
assert model.n_features_in_==48 and model.classes_.tolist()==[0,1] and np.isfinite(probability).all()
with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({'ready':True,'interpreter':sys.executable,'sklearnVersion':m.version('scikit-learn'),'features':48,'classes':[0,1],'trees':len(model.estimators_),'modelSha256':checksum,'versionWarnings':sorted(set(str(item.message) for item in observed))}))
"""
    raw = Executor(config, execute=True).ssh(
        [config["server"]["python"], "-c", source],
        payload=json.dumps({"assets": ASSETS}).encode(),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(raw)
    value = json.loads(raw)
    print(
        json.dumps(
            {
                key: value[key]
                for key in (
                    "ready",
                    "sklearnVersion",
                    "features",
                    "classes",
                    "modelSha256",
                )
            }
        )
    )
