"""Read a 15-band GeoTIFF, call the delivered forward(), and write a classified GeoTIFF."""

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Callable, BinaryIO

import numpy as np
from osgeo import gdal

# ==================== CONFIGURATION ====================
HERE = Path(__file__).resolve().parent
INPUT_TIF = HERE / "input_b15.tif"
WEIGHTS = HERE / "DeepLabv3_plus_SEBlock_all_Planet_8B_250924_TJK_1024_b15.pth"
PROFILE_JSON = HERE / "推理配置.json"
OUTPUT_DIR = HERE / "result-b15"
DEVICE = "cpu"  # Set to cuda only with an available, authorized GPU runtime.
# ==================== MODEL AND OUTPUT CONTRACT ====================
ARCH_FILE = "DeepLabv3_plus_SEBlock.py"
ARCH_SHA256 = "604fb5d9512d602e1d9633553d2c77b853d3954c82578e1d9a1edb60e13c56e8"
WEIGHTS_SHA256 = "6442cb41dcaf68ab11621354089297c2f748a88183ba3e79ae717bd1450acdc7"
CHANNELS = 15
RES_METRES = 3
MAX_PIXELS = 30_000_000
NODATA = 255
LEGEND = [
    {"code": 0, "name": "背景", "rgba": [0, 0, 0, 0]},
    {"code": 1, "name": "洁净冰川", "rgba": [75, 173, 232, 255]},
    {"code": 2, "name": "表碛冰川", "rgba": [234, 183, 100, 255]},
    {"code": NODATA, "name": "缺测", "rgba": [0, 0, 0, 0]},
]


@dataclass(frozen=True)
class Profile:
    purpose: str
    evidence: str
    bands: tuple[int, ...]
    gain: tuple[float, ...]
    bias: tuple[float, ...]
    tile: int
    halo: int
    edge: str
    fill: float
    mask: str

    @classmethod
    def parse(cls, document):
        keys = {
            "schemaVersion",
            "purpose",
            "evidence",
            "bands",
            "gain",
            "bias",
            "tile",
            "halo",
            "edge",
            "fill",
            "mask",
            "stitch",
        }
        if (
            not isinstance(document, dict)
            or document.keys() != keys
            or type(document["schemaVersion"]) is not int
            or document["schemaVersion"] != 1
        ):
            raise ValueError("推理配置字段或版本不符。")
        p = document
        if (
            p["purpose"] not in ("engineering", "reference")
            or not isinstance(p["evidence"], str)
            or not 8 <= len(p["evidence"].strip()) <= 500
            or any(ord(ch) < 32 for ch in p["evidence"])
            or p["stitch"] != "center_crop"
        ):
            raise ValueError(
                "必须明确用途、配置出处和 center_crop 拼接方式；不得假定训练规约。"
            )
        if (
            not isinstance(p["bands"], list)
            or len(p["bands"]) != CHANNELS
            or any(type(v) is not int for v in p["bands"])
            or set(p["bands"]) != set(range(1, CHANNELS + 1))
        ):
            raise ValueError("bands须明确填写1至15各原始波段在模型中的排列。")
        for key in ("gain", "bias"):
            if (
                not isinstance(p[key], list)
                or len(p[key]) != CHANNELS
                or any(
                    type(v) not in (int, float) or not -1000 <= v <= 1000
                    for v in p[key]
                )
            ):
                raise ValueError("每个通道须明确填写有界的归一化系数与偏置。")
        if any(gain == 0 for gain in p["gain"]):
            raise ValueError("gain不能为0；请检查通道预处理配置。")
        tile, halo, fill = p["tile"], p["halo"], p["fill"]
        if (
            type(tile) is not int
            or not 32 <= tile <= 1024
            or tile % 8
            or type(halo) is not int
            or not 0 <= halo < tile // 2
            or tile - 2 * halo < 16
            or type(fill) not in (int, float)
            or not -1000 <= fill <= 1000
            or p["edge"] not in ("constant", "edge")
            or p["mask"] not in ("require_explicit", "trust_all_valid_metadata")
        ):
            raise ValueError("切窗、边缘填充或有效掩膜配置不符。")
        return cls(
            p["purpose"],
            p["evidence"].strip(),
            tuple(p["bands"]),
            tuple(p["gain"]),
            tuple(p["bias"]),
            tile,
            halo,
            p["edge"],
            fill,
            p["mask"],
        )

    @property
    def sha256(self):
        from dataclasses import asdict

        payload = {"schemaVersion": 1, "stitch": "center_crop", **asdict(self)}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()


def build_predictor(
    stream: BinaryIO, device: str = "cpu"
) -> Callable[[np.ndarray], np.ndarray]:
    """Verify the pinned bytes, load the state dict exactly, use delivered forward unchanged."""
    state_identity = os.fstat(stream.fileno())
    if not stream.seekable():
        raise ValueError("权重须为可校验的只读文件。")
    stream.seek(0)
    if hashlib.file_digest(stream, "sha256").hexdigest() != WEIGHTS_SHA256:
        raise ValueError("权重与15波段交接版的登记摘要不一致。")
    stream.seek(0)
    code = (HERE / ARCH_FILE).read_bytes()
    if hashlib.sha256(code).hexdigest() != ARCH_SHA256:
        raise ValueError("网络代码与交接版摘要不一致。")
    import torch

    if device not in ("cpu", "cuda") or (
        device == "cuda" and not torch.cuda.is_available()
    ):
        raise ValueError("请选择可用的CPU或已授权CUDA设备。")
    checkpoint = torch.load(stream, map_location="cpu", weights_only=True)
    after = os.fstat(stream.fileno())
    if (
        state_identity.st_ino,
        state_identity.st_size,
        state_identity.st_mtime_ns,
        state_identity.st_ctime_ns,
    ) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("权重在读取期间发生变化。")
    if (
        not isinstance(checkpoint, dict)
        or not checkpoint
        or any(
            not isinstance(k, str) or not isinstance(v, torch.Tensor)
            for k, v in checkpoint.items()
        )
    ):
        raise ValueError("交接权重必须为张量 state_dict。")
    state = {k.removeprefix("module."): v for k, v in checkpoint.items()}
    if len(state) != len(checkpoint):
        raise ValueError("权重键去除module前缀后重复。")
    namespace = {"__name__": "verified_glacier_b15"}
    exec(compile(code, ARCH_FILE, "exec"), namespace)
    model = namespace["DeepLabv3_plus_SEBlock"](num_classes=3, band_num=CHANNELS, os=8)
    model.load_state_dict(state, strict=True)
    model.eval().to(device)

    def predict(batch):
        with torch.inference_mode():
            result = model(torch.from_numpy(batch).to(device))
            return result.to(device="cpu", dtype=torch.float32).numpy()

    return predict


def validate_source(source, p: Profile):
    ref = source.GetSpatialRef()
    transform = source.GetGeoTransform(can_return_null=True)
    authority = (
        ref.GetAuthorityCode(None)
        if ref and ref.GetAuthorityName(None) == "EPSG"
        else None
    )
    zone = int(authority) if authority and authority.isdecimal() else 0
    if (
        source.GetDriver().ShortName != "GTiff"
        or source.RasterCount != CHANNELS
        or ref is None
        or not ref.IsProjected()
        or not (32601 <= zone <= 32660 or 32701 <= zone <= 32760)
        or not math.isclose(ref.GetLinearUnits(), 1)
        or transform is None
        or not np.isfinite(transform).all()
        or (transform[1], transform[2], transform[4], transform[5])
        != (RES_METRES, 0, 0, -RES_METRES)
        or any(source.GetRasterBand(band).DataType != gdal.GDT_Byte for band in p.bands)
        or not 1 <= source.RasterXSize * source.RasterYSize <= MAX_PIXELS
    ):
        raise ValueError(
            "输入须为原始15波段UInt8、3米北向上WGS 84 / UTM GeoTIFF，且像元数不超过3000万。"
        )
    bands = [source.GetRasterBand(band) for band in p.bands]
    masks = []
    per_dataset = False
    for band in bands:
        flags = band.GetMaskFlags()
        if flags & gdal.GMF_ALL_VALID:
            continue
        if flags & gdal.GMF_PER_DATASET:
            if per_dataset:
                continue
            per_dataset = True
        masks.append(band.GetMaskBand())
    if not masks and p.mask == "require_explicit":
        raise ValueError(
            "源影像没有可用的显式有效掩膜或NoData声明，不能把全图默认视为有效。"
        )
    return transform, ref, bands, masks


def window_input(bands, mask_bands, x, y, width, height, p):
    # Read only in-range source pixels; padding never contributes output pixels.
    valid = np.ones((height, width), dtype=bool)
    for mb in mask_bands:
        valid &= mb.ReadAsArray(x, y, width, height) != 0
    data = np.empty((CHANNELS, height, width), dtype=np.float32)
    for i, b in enumerate(bands):
        np.multiply(
            b.ReadAsArray(x, y, width, height), np.float32(p.gain[i]), out=data[i]
        )
        data[i] += np.float32(p.bias[i])
    data[:, ~valid] = p.fill
    return data, valid


def classify_geotiff(source_path: Path, output_path: Path, profile: Profile, predict):
    """Classify disjoint core windows, retaining original geometry and valid background 0."""
    if (
        output_path.exists()
        or output_path.is_symlink()
        or source_path.resolve() == output_path.resolve()
    ):
        raise FileExistsError("只允许创建新的分类输出，不覆盖现有文件或输入。")
    gdal.UseExceptions()
    source = gdal.OpenEx(
        str(source_path), gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=["GTiff"]
    )
    transform, ref, bands, mask_bands = validate_source(source, profile)
    width, height = source.RasterXSize, source.RasterYSize
    size = profile.tile
    halo = profile.halo
    core = size - 2 * halo
    dest = None
    counts = np.zeros(256, dtype=np.int64)
    tiles = 0
    with tempfile.TemporaryDirectory(prefix=".mask-", dir=output_path.parent) as work:
        partial = Path(work) / "classification.tif"
        try:
            dest = gdal.GetDriverByName("GTiff").Create(
                str(partial),
                width,
                height,
                1,
                gdal.GDT_Byte,
                ["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
            )
            dest.SetGeoTransform(transform)
            dest.SetSpatialRef(ref)
            dest.SetMetadataItem(
                "stisp_categorical",
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "legend": LEGEND,
                        "transparentValues": [0, NODATA],
                    },
                    ensure_ascii=False,
                ),
            )
            dest.SetMetadataItem("glacier_profile_sha256", profile.sha256)
            dest.SetMetadataItem("glacier_profile_purpose", profile.purpose)
            band = dest.GetRasterBand(1)
            band.SetNoDataValue(NODATA)
            table = gdal.ColorTable()
            for item in LEGEND:
                table.SetColorEntry(item["code"], tuple(item["rgba"]))
            band.SetColorTable(table)
            band.SetColorInterpretation(gdal.GCI_PaletteIndex)
            for topl in range(0, height, core):
                for left in range(0, width, core):
                    h, w = min(core, height - topl), min(core, width - left)
                    nominal_x, nominal_y = left - halo, topl - halo
                    x, y = max(nominal_x, 0), max(nominal_y, 0)
                    end_x, end_y = (
                        min(nominal_x + size, width),
                        min(nominal_y + size, height),
                    )
                    off_x, off_y = x - nominal_x, y - nominal_y
                    read_width, read_height = end_x - x, end_y - y
                    local_x, local_y = left - x, topl - y
                    data, valid = window_input(
                        bands, mask_bands, x, y, read_width, read_height, profile
                    )
                    center = valid[local_y : local_y + h, local_x : local_x + w]
                    tile_output = np.full((h, w), NODATA, np.uint8)
                    if center.any():
                        pads = (
                            (0, 0),
                            (off_y, size - off_y - read_height),
                            (off_x, size - off_x - read_width),
                        )
                        if any(pad != (0, 0) for pad in pads):
                            opts = (
                                {"constant_values": profile.fill}
                                if profile.edge == "constant"
                                else {}
                            )
                            data = np.pad(data, pads, mode=profile.edge, **opts)
                        result = predict(np.ascontiguousarray(data[None, ...]))
                        if (
                            result.shape != (1, 3, size, size)
                            or not np.isfinite(result).all()
                            or np.any(result < 0)
                            or not np.allclose(result.sum(axis=1), 1, rtol=0, atol=1e-5)
                        ):
                            raise ValueError(
                                "模型未返回有效的三类逐像元概率；不生成正式分类。"
                            )
                        classes = result[0, :, halo : halo + h, halo : halo + w].argmax(
                            axis=0
                        )
                        tile_output[center] = classes[center]
                        tiles += 1
                    band.WriteArray(tile_output, left, topl)
                    counts += np.bincount(tile_output.ravel(), minlength=256)
            if not counts[:3].sum():
                raise ValueError("全幅没有有效观测像元。")
            dest.FlushCache()
            band = None
            dest = None

            with gdal.OpenEx(str(partial), gdal.OF_RASTER | gdal.OF_READONLY) as check:
                if (
                    check.GetGeoTransform() != transform
                    or not check.GetSpatialRef().IsSame(ref)
                    or (check.RasterXSize, check.RasterYSize) != (width, height)
                    or check.RasterCount != 1
                    or check.GetRasterBand(1).GetNoDataValue() != NODATA
                    or counts.sum() != width * height
                ):
                    raise RuntimeError("输出尺寸、投影、网格、NoData或计数与合同不符。")
            os.link(partial, output_path)
        finally:
            # Close the destination before TemporaryDirectory releases partial files.
            dest = None
    return {
        "width": width,
        "height": height,
        "classCounts": {str(i): int(counts[i]) for i in (0, 1, 2, NODATA)},
        "modelWindows": tiles,
        "hasExplicitMask": bool(mask_bands),
    }


def run_files(
    input_tif: Path, weight_path: Path, profile: Profile, out: Path, device: str
):
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    with weight_path.open("rb") as stream:
        predictor = build_predictor(stream, device)
    stats = classify_geotiff(input_tif, out / "classification.tif", profile, predictor)
    completion = {
        "purpose": profile.purpose,
        "profileSha256": profile.sha256,
        "checkpointSha256": WEIGHTS_SHA256,
        "architectureSha256": ARCH_SHA256,
        "eligibleForOfficialPublication": False,
        "qualityStatus": "needs_review",
        **stats,
    }
    with (out / "inference-receipt.json").open("x", encoding="utf-8") as f:
        json.dump(completion, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return completion


def main():
    if not PROFILE_JSON.is_file():
        raise FileNotFoundError(
            "请先按配置模板填写推理配置.json；不会回退到工程测试参数。"
        )
    if PROFILE_JSON.stat().st_size > 65536:
        raise ValueError("推理配置大小超限。")
    profile = Profile.parse(json.loads(PROFILE_JSON.read_text(encoding="utf-8")))
    output = run_files(INPUT_TIF, WEIGHTS, profile, OUTPUT_DIR, DEVICE)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
