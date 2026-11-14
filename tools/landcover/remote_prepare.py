"""Asset extraction and a small, isolated GPU compatibility check; no deployment."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

# ==================== CONFIGURATION ====================
CONFIG = json.load(sys.stdin)
PREFIX = "landcover_inference_handoff_20261114/"
# =======================================================
root = Path(CONFIG["assets"])
root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(CONFIG["package"]) as archive:
    manifest = json.loads(archive.read(PREFIX + "models/model_manifest.json"))
    for record in manifest["weights"]:
        relative = "models/" + record["file"]
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assert (
                hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
                == record["sha256"]
            ), "Existing model asset differs"
        else:
            content = archive.read(PREFIX + relative)
            assert hashlib.sha256(content).hexdigest() == record["sha256"]
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            path.chmod(0o444)
    for relative in [
        "config/models.json",
        "config/postprocess.json",
        "models/model_manifest.json",
    ]:
        content = archive.read(PREFIX + relative)
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assert path.read_bytes() == content
        else:
            path.write_bytes(content)
            path.chmod(0o444)
    network = root / "compat-unet.py"
    if network.exists():
        assert network.read_text() == CONFIG["networkSource"]
    else:
        network.write_text(CONFIG["networkSource"])
        network.chmod(0o444)
query = r"""
import fcntl,hashlib,importlib.metadata,json,os,subprocess,sys
from pathlib import Path
config=json.loads(sys.argv[1]);root=Path(config['assets'])
rows=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,memory.used','--format=csv,noheader,nounits'],text=True).splitlines()
row=next(line.split(',') for line in rows if int(line.split(',')[0])==config['gpuIndex'])
assert int(row[2])<1024, 'Compatibility GPU is already occupied'
lock=open(root/('gpu-'+row[1].strip()+'.lock'),'a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
os.environ['CUDA_VISIBLE_DEVICES']=row[1].strip();os.environ['PYTHONNOUSERSITE']='1';os.environ['OMP_NUM_THREADS']='2'
import importlib.util
spec=importlib.util.find_spec('pyproj')
proj=Path(sys.prefix)/'share/proj'
if not (proj/'proj.db').is_file():proj=Path(spec.origin).parent/'proj_dir/share/proj' if spec else Path('/usr/share/proj')
assert (proj/'proj.db').is_file(), 'PROJ database is missing'
os.environ['PROJ_DATA']=str(proj);os.environ['PROJ_LIB']=str(proj)
import torch,numpy,scipy,PIL
from osgeo import gdal,osr
osr.UseExceptions();osr.SetPROJSearchPaths([str(proj)])
namespace={};exec(compile((root/'compat-unet.py').read_text(),'provided-unet','exec'),namespace)
manifest=json.loads((root/'models/model_manifest.json').read_text());models=[]
with torch.inference_mode():
 for weight in manifest['weights']:
  state=torch.load(root/'models'/weight['file'],map_location='cpu',weights_only=True,mmap=True)
  state={key.removeprefix('module.'):value for key,value in state.items()}
  model=namespace['UNet'](band_num=3,num_classes=2);model.load_state_dict(state,strict=True);model.eval().to('cuda:0')
  output=model(torch.zeros((1,3,64,64),device='cuda:0'));torch.cuda.synchronize()
  assert tuple(output.shape)==(1,2,64,64) and bool(torch.isfinite(output).all())
  models.append({'name':weight['name'],'strictLoad':True,'outputShape':list(output.shape)})
  del output,model,state;torch.cuda.empty_cache()
srs=osr.SpatialReference();assert srs.ImportFromEPSG(4326)==0
print(json.dumps({'ready':True,'python':sys.version.split()[0],'torch':torch.__version__,'cuda':torch.version.cuda,'numpy':numpy.__version__,'scipy':scipy.__version__,'gdal':gdal.VersionInfo('RELEASE_NAME'),'gpuUuid':row[1].strip(),'gpuName':torch.cuda.get_device_name(0),'models':models,'weightsOnly':True,'projData':str(proj),'gdalData':str(Path(sys.prefix)/'share/gdal')}))
"""
result = subprocess.run(
    [CONFIG["interpreter"], "-s", "-c", query, json.dumps(CONFIG)],
    capture_output=True,
    text=True,
    timeout=180,
)
if result.returncode:
    print(
        json.dumps(
            {"ready": False, "error": result.stderr[-4000:], "assets": str(root)},
            ensure_ascii=False,
        )
    )
else:
    print(result.stdout.strip().splitlines()[-1])
