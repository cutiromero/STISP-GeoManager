"""Compare explicit preprocessing and target-period hypotheses on native SeasFire."""

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import resource
import time

import numpy as np

# CONFIGURATION
SOURCE = Path(
    "/root/autodl-tmp/geomanager-data-20260919/research/projects/13/raster/original/imported/wildfire-handoff-20261114/seasfire_v0.4.zarr"
)
WEIGHTS = Path(
    "/root/autodl-tmp/geomanager-data-20260919/research/handoffs/wildfire_handoff_20261114/野火数据/climafire-demo/models"
)
OUTPUT = Path("/root/autodl-tmp/wildfire-analysis/comparison_20261115_final")
VARIABLES = [
    "mslp",
    "tp",
    "vpd",
    "sst",
    "t2m_mean",
    "ssrd",
    "swvl1",
    "lst_day",
    "ndvi",
    "pop_dens",
    "lsm",
]
METHODS = [
    "raw_zero",
    "standard_zero",
    "standard_minus_one",
    "minmax_zero",
    "minmax_minus_one",
]
WINDOWS = [1, 2, 4, 8, 16]
FIT_TIME_COUNT = 46
FIT_TIME_STEP = 16
SPATIAL_STEP = 8
SEED = 20261115
THREADS = 4
# 2018/2019 are exploratory comparison; 2020 remains a separately reported holdout.
REGIONS = [
    {
        "name": "australia",
        "row": 400,
        "col": 1168,
        "height": 128,
        "width": 192,
        "first": 827,
    },
    {
        "name": "brazil",
        "row": 340,
        "col": 400,
        "height": 128,
        "width": 160,
        "first": 810,
    },
    {
        "name": "southern_africa",
        "row": 340,
        "col": 760,
        "height": 128,
        "width": 160,
        "first": 810,
    },
]


class Reader:
    def __init__(self):
        from osgeo import gdal

        gdal.UseExceptions()
        self.metadata = json.loads((SOURCE / ".zmetadata").read_text())["metadata"]
        self.dataset = gdal.OpenEx(str(SOURCE), gdal.OF_MULTIDIM_RASTER)
        self.group = self.dataset.GetRootGroup()

    def read(self, name, start, count, step=None):
        schema = self.metadata[name + "/.zarray"]
        if math.prod(count) * np.dtype(schema["dtype"]).itemsize > 128 * 1024**2:
            raise ValueError("Requested observation exceeds bounded read budget")
        raw = self.group.OpenMDArray(name).Read(
            array_start_idx=start, count=count, array_step=step or [1] * len(count)
        )
        values = (
            np.frombuffer(raw, dtype=np.dtype(schema["dtype"]).newbyteorder("="))
            .reshape(count)
            .copy()
        )
        attributes = self.metadata[name + "/.zattrs"]
        for missing in [
            schema.get("fill_value"),
            attributes.get("missing_value"),
            attributes.get("_FillValue"),
        ]:
            if isinstance(missing, (int, float)) and math.isfinite(missing):
                values[values == missing] = np.nan
        return values

    def drivers(self, name, region=None):
        dimensions = self.metadata[name + "/.zattrs"]["_ARRAY_DIMENSIONS"]
        if region is None:
            if len(dimensions) == 3:
                return self.read(
                    name,
                    [0, 4, 4],
                    [FIT_TIME_COUNT, 90, 180],
                    [FIT_TIME_STEP, SPATIAL_STEP, SPATIAL_STEP],
                )
            return np.broadcast_to(
                self.read(name, [4, 4], [90, 180], [SPATIAL_STEP, SPATIAL_STEP]),
                (FIT_TIME_COUNT, 90, 180),
            )
        start = [region["row"], region["col"]]
        count = [region["height"], region["width"]]
        if len(dimensions) == 3:
            return self.read(name, [region["first"], *start], [3, *count], [46, 1, 1])
        return np.broadcast_to(self.read(name, start, count), (3, *count))


def normalize(raw, statistics, method):
    result = np.array(raw, dtype="float32", copy=True)
    for channel, name in enumerate(VARIABLES):
        values = result[:, channel]
        stats = statistics[name]
        if name != "lsm":
            if method.startswith("standard"):
                values -= stats["mean"]
                values /= max(stats["std"], 1e-6)
            elif method.startswith("minmax"):
                values -= stats["min"]
                values /= max(stats["max"] - stats["min"], 1e-6)
                if method.endswith("minus_one"):
                    values *= 2
                    values -= 1
        np.nan_to_num(
            values,
            copy=False,
            nan=-1 if method.endswith("minus_one") and name != "lsm" else 0,
            posinf=0,
            neginf=0,
        )
    return result


def metrics(labels, probabilities):
    from sklearn.metrics import average_precision_score, roc_auc_score

    labels = labels.astype(bool)
    if not len(labels) or labels.all() or not labels.any():
        return {
            "cells": len(labels),
            "positiveCells": int(labels.sum()),
            "auc": None,
            "ap": None,
        }
    binary = probabilities >= 0.5
    tp = int((labels & binary).sum())
    return {
        "cells": len(labels),
        "positiveCells": int(labels.sum()),
        "prevalence": float(labels.mean()),
        "auc": float(roc_auc_score(labels, probabilities)),
        "ap": float(average_precision_score(labels, probabilities)),
        "brier": float(np.mean((labels - probabilities) ** 2)),
        "precisionAtHalf": tp / max(1, int(binary.sum())),
        "recallAtHalf": tp / int(labels.sum()),
        "predictedPositiveFraction": float(binary.mean()),
        "meanProbability": float(probabilities.mean()),
    }


def main():
    import torch
    import torch.nn.functional as functional
    import segmentation_models_pytorch as smp

    started = time.monotonic()
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(THREADS)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reader = Reader()
    statistics, samples = {}, []
    for name in VARIABLES:
        values = reader.drivers(name).astype("float32")
        finite = values[np.isfinite(values)].astype("float64")
        statistics[name] = {
            "mean": float(finite.mean()),
            "std": float(finite.std()),
            "min": float(finite.min()),
            "max": float(finite.max()),
            "missingFraction": float(1 - len(finite) / values.size),
        }
        samples.append(values)
        print(
            json.dumps(
                {"phase": "fit_statistics", "variable": name, **statistics[name]}
            ),
            flush=True,
        )
    sample = np.stack(samples, axis=1)
    del samples
    report = {
        "source": str(SOURCE),
        "sourceMetadataSha256": hashlib.sha256(
            (SOURCE / ".zmetadata").read_bytes()
        ).hexdigest(),
        "codeSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seed": SEED,
        "variableOrderHypothesis": VARIABLES,
        "fit": {
            "timeStart": 0,
            "count": FIT_TIME_COUNT,
            "step": FIT_TIME_STEP,
            "spatialStep": SPATIAL_STEP,
        },
        "splits": {"exploratoryYears": [2018, 2019], "holdoutYears": [2020]},
        "statistics": statistics,
        "stemComparisons": [],
        "evaluations": [],
        "versions": {
            name: importlib.metadata.version(name)
            for name in [
                "torch",
                "numpy",
                "segmentation-models-pytorch",
                "timm",
                "GDAL",
                "scikit-learn",
            ]
        },
        "interpretation": "Explicit hypotheses; validation performance does not recover the missing original training specification.",
    }
    model = smp.UnetPlusPlus(
        encoder_name="efficientnet-b5", encoder_weights=None, in_channels=11, classes=1
    ).eval()
    for window in WINDOWS:
        path = WEIGHTS / f"unet_w{window}.ckpt"
        checkpoint = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
        state = {
            key.removeprefix("net."): value
            for key, value in checkpoint["state_dict"].items()
        }
        model.load_state_dict(state, strict=True)
        weight, mean, variance = (
            state["encoder._conv_stem.weight"],
            state["encoder._bn0.running_mean"],
            state["encoder._bn0.running_var"],
        )
        implied_mean = torch.linalg.lstsq(
            weight.sum((-1, -2)).double(), mean.double()
        ).solution.numpy()
        for method in METHODS:
            with torch.inference_mode():
                activation = functional.conv2d(
                    torch.from_numpy(normalize(sample, statistics, method)),
                    weight,
                    stride=2,
                    padding=1,
                )[:, :, 1:-1, 1:-1]
                actual_mean = activation.mean((0, 2, 3))
                actual_var = activation.var((0, 2, 3), unbiased=False)
                distance = float(
                    (
                        ((actual_mean - mean) ** 2 / variance.clamp_min(1e-5)).mean()
                        + torch.log(
                            actual_var.clamp_min(1e-5) / variance.clamp_min(1e-5)
                        )
                        .square()
                        .mean()
                    ).item()
                )
            row = {
                "weight": window,
                "method": method,
                "stemMomentDistance": distance,
                "impliedInputMean": implied_mean.tolist(),
            }
            report["stemComparisons"].append(row)
            print(json.dumps({"phase": "stem", **row}), flush=True)
        del checkpoint, state
    del sample
    for region in REGIONS:
        drivers = np.stack([reader.drivers(name, region) for name in VARIABLES], axis=1)
        length = 2 * 46 + 17
        labels = reader.read(
            "gwis_ba",
            [region["first"], region["row"], region["col"]],
            [length, region["height"], region["width"]],
        )
        for window in WINDOWS:
            checkpoint = torch.load(
                WEIGHTS / f"unet_w{window}.ckpt",
                map_location="cpu",
                weights_only=True,
                mmap=True,
            )
            model.load_state_dict(
                {
                    key.removeprefix("net."): value
                    for key, value in checkpoint["state_dict"].items()
                },
                strict=True,
            )
            del checkpoint
            for method in ["standard_minus_one", "standard_zero", "minmax_minus_one"]:
                with torch.inference_mode():
                    prediction = torch.sigmoid(
                        model(torch.from_numpy(normalize(drivers, statistics, method)))
                    )[:, 0].numpy()
                assert np.isfinite(prediction).all()
                for year_index in range(3):
                    base = year_index * 46
                    land = np.isfinite(drivers[year_index, -1]) & (
                        drivers[year_index, -1] > 0.5
                    )
                    for lead in [0, 1, 2, 4, 8, 16]:
                        truth = labels[base + lead]
                        valid = land & np.isfinite(truth) & np.isfinite(labels[base])
                        report["evaluations"].append(
                            {
                                "region": region["name"],
                                "year": 2018 + year_index,
                                "weight": window,
                                "method": method,
                                "target": "single_period",
                                "leadPeriods": lead,
                                "persistence": metrics(
                                    truth[valid] > 0,
                                    (labels[base][valid] > 0).astype("float32"),
                                ),
                                **metrics(
                                    truth[valid] > 0, prediction[year_index][valid]
                                ),
                            }
                        )
                    for horizon in [1, 2, 4, 8, 16]:
                        future = labels[base + 1 : base + horizon + 1]
                        valid = (
                            land
                            & np.isfinite(future).all(0)
                            & np.isfinite(labels[base])
                        )
                        report["evaluations"].append(
                            {
                                "region": region["name"],
                                "year": 2018 + year_index,
                                "weight": window,
                                "method": method,
                                "target": "cumulative_future",
                                "leadPeriods": horizon,
                                "persistence": metrics(
                                    (future > 0).any(0)[valid],
                                    (labels[base][valid] > 0).astype("float32"),
                                ),
                                **metrics(
                                    (future > 0).any(0)[valid],
                                    prediction[year_index][valid],
                                ),
                            }
                        )
                print(
                    json.dumps(
                        {
                            "phase": "inference",
                            "region": region["name"],
                            "weight": window,
                            "method": method,
                        }
                    ),
                    flush=True,
                )
                (OUTPUT / "comparison.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
    report["elapsedSeconds"] = time.monotonic() - started
    report["peakRssKiB"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["complete"] = True
    (OUTPUT / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "complete": True,
                "elapsedSeconds": report["elapsedSeconds"],
                "output": str(OUTPUT),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
