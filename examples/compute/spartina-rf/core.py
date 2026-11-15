"""Three-season RF interpretation on a bounded original WGS84 grid."""

from contextlib import ExitStack, closing
from pathlib import Path

# CONFIGURATION
BANDS = [
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B9",
    "B11",
    "B12",
    "NDVI",
    "NDWI",
    "NBR",
    "EVI",
]
ROLES = ["march", "august", "december"]
BLOCK_SIZE = 256
CONCURRENT_TILES = 8
GDAL_CACHE_MIB = 256
COLOR = "#65D8A4"


def infer(paths, model, output, progress=lambda *_: None):
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from pyproj import Geod
    from rf_streaming import StreamingPatchCounter, InvalidTileCache

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    classes = np.asarray(model.classes_)
    if model.n_features_in_ != 48 or classes.tolist() != [0, 1]:
        raise ValueError("权重须为48特征、0/1分类的互花米草模型")
    with ExitStack() as stack:
        stack.enter_context(
            rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MIB * 1024**2, GDAL_PAM_ENABLED="NO")
        )
        sources = [stack.enter_context(rasterio.open(paths[role])) for role in ROLES]
        first = sources[0]
        grid = (first.width, first.height, first.transform, first.crs)
        if first.crs.to_epsg() != 4326 or first.transform.b or first.transform.d:
            raise ValueError("输入须为有界北向上WGS84原始窗口")
        for source in sources:
            if (
                source.width,
                source.height,
                source.transform,
                source.crs,
            ) != grid or source.count != 16:
                raise ValueError("三个季节须具有一致原始网格及16波段")
            if (
                any(name is not None for name in source.descriptions)
                and list(source.descriptions) != BANDS
            ):
                raise ValueError("输入波段顺序与交付RF特征不一致")
        profile = {
            **first.profile,
            "driver": "GTiff",
            "count": 1,
            "dtype": "uint8",
            "nodata": 255,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
            "BIGTIFF": "IF_SAFER",
            "SPARSE_OK": "YES",
        }
        classification = stack.enter_context(
            rasterio.open(output / "classification.tif", "w", **profile)
        )
        probability = stack.enter_context(
            rasterio.open(
                output / "probability.tif",
                "w",
                **{**profile, "dtype": "float32", "nodata": -9999},
            )
        )
        classification.write_colormap(
            1, {0: (0, 0, 0, 0), 1: (101, 216, 164, 255), 255: (0, 0, 0, 0)}
        )
        import json

        classification.update_tags(
            stisp_categorical=json.dumps(
                {
                    "schemaVersion": 1,
                    "legend": [
                        {"code": 0, "name": "非目标区", "rgba": [0, 0, 0, 0]},
                        {"code": 1, "name": "互花米草", "rgba": [101, 216, 164, 255]},
                        {"code": 255, "name": "无效区", "rgba": [0, 0, 0, 0]},
                    ],
                    "transparentValues": [0, 255],
                },
                ensure_ascii=False,
            )
        )
        patches = StreamingPatchCounter(first.width)
        invalid_caches = [
            stack.enter_context(closing(InvalidTileCache(paths[role])))
            for role in ROLES
        ]
        skipped = 0
        target_per_row = np.zeros(first.height, dtype=np.int64)
        valid_per_row = np.zeros(first.height, dtype=np.int64)
        total = ((first.width + 255) // 256) * ((first.height + 255) // 256)
        from collections import deque
        from concurrent.futures import ThreadPoolExecutor, Future
        from sklearn.ensemble import RandomForestClassifier

        def read_blocks():
            for row in range(0, first.height, BLOCK_SIZE):
                for col in range(0, first.width, BLOCK_SIZE):
                    height, width = (
                        min(BLOCK_SIZE, first.height - row),
                        min(BLOCK_SIZE, first.width - col),
                    )
                    window = Window(col, row, width, height)
                    blocks = []
                    skip = False
                    for source, cache in zip(sources, invalid_caches):
                        signature = cache.signature(row, col, height, width)
                        if signature in cache.empty:
                            skip = True
                            break
                        block = source.read(window=window, masked=True).astype(
                            "float32"
                        )
                        cache.remember(signature, block, source.nodatavals)
                        blocks.append(block)
                        if (
                            signature in cache.empty
                            or not np.isfinite(block.filled(np.nan)).all(axis=0).any()
                        ):
                            skip = True
                            break
                    if skip:
                        yield (row, col, height, width, None, None)
                        continue
                    values = np.ma.concatenate(blocks, axis=0)
                    features = values.filled(np.nan).reshape(48, -1).T
                    valid = np.isfinite(features).all(axis=1)
                    yield (row, col, height, width, features[valid], valid)

        def predict_block(record):
            row, col, height, width, data, valid = record
            if data is None:
                return (row, col, height, width, None, None)
            result = np.full(height * width, 255, dtype="uint8")
            chance = np.full(height * width, -9999, dtype="float32")
            if len(data):
                distribution = model.predict_proba(data)
                prediction = (
                    classes.take(np.argmax(distribution, axis=1), axis=0)
                    if type(model) is RandomForestClassifier
                    else model.predict(data)
                )
                probabilities = distribution[:, int(np.flatnonzero(classes == 1)[0])]
                if (
                    not np.isfinite(probabilities).all()
                    or (probabilities < 0).any()
                    or (probabilities > 1).any()
                    or not np.isin(prediction, [0, 1]).all()
                ):
                    raise ValueError("模型输出不是有效分类与概率")
                result[valid] = prediction
                chance[valid] = probabilities
            return (
                row,
                col,
                height,
                width,
                result.reshape(height, width),
                chance.reshape(height, width),
            )

        def predictions():
            pending = deque()
            with ThreadPoolExecutor(max_workers=CONCURRENT_TILES) as executor:
                for record in read_blocks():
                    if record[4] is None:
                        future = Future()
                        future.set_result(predict_block(record))
                    else:
                        future = executor.submit(predict_block, record)
                    pending.append(future)
                    if len(pending) >= CONCURRENT_TILES:
                        yield pending.popleft().result()
                while pending:
                    yield pending.popleft().result()

        count = 0
        for row, col, height, width, result, chance in predictions():
            if result is None:
                skipped += 1
                patches.add(None, row, col, height, width)
            else:
                target = result == 1
                patches.add(target, row, col, height, width)
                target_per_row[row : row + height] += target.sum(axis=1)
                valid_per_row[row : row + height] += (result != 255).sum(axis=1)
                window = Window(col, row, width, height)
                classification.write(result, 1, window=window)
                probability.write(chance, 1, window=window)
            count += 1
            progress("模型解译", 30 + int(count / total * 40))
        if first.width * first.height <= 4194304:
            # A display-only RGB preview of the actual August window; model features stay unchanged.
            preview_values = sources[1].read([4, 3, 2], masked=True)
            rgb = np.zeros((3, first.height, first.width), dtype="uint8")
            for index in range(3):
                valid_values = preview_values[index].compressed()
                valid_values = valid_values[np.isfinite(valid_values)]
                if valid_values.size:
                    low, high = np.percentile(
                        valid_values[:: max(1, valid_values.size // 20000)], [2, 98]
                    )
                    high = max(high, low + 1e-6)
                    rgb[index] = (
                        np.clip(
                            (preview_values[index].filled(low) - low) / (high - low),
                            0,
                            1,
                        )
                        * 255
                    ).astype("uint8")
            with rasterio.open(
                output / "original.tif",
                "w",
                **{**profile, "count": 3, "dtype": "uint8", "nodata": None},
            ) as preview:
                preview.write(rgb)
                preview.write_mask(
                    (~np.ma.getmaskarray(preview_values).any(axis=0)).astype("uint8")
                    * 255
                )
                preview.colorinterp = (
                    rasterio.enums.ColorInterp.red,
                    rasterio.enums.ColorInterp.green,
                    rasterio.enums.ColorInterp.blue,
                )
                preview.update_tags(stisp_imagery="rgb")
        if first.width * first.height > 4194304:
            progress("准备显示概览", 75)
            classification.close()
            probability.close()
            for filename in ("classification.tif", "probability.tif"):
                with (
                    rasterio.Env(
                        COMPRESS_OVERVIEW="DEFLATE",
                        SPARSE_OK_OVERVIEW="YES",
                        GDAL_NUM_THREADS=str(CONCURRENT_TILES),
                    ),
                    rasterio.open(output / filename, "r+") as display,
                ):
                    levels = [
                        factor
                        for factor in (32, 64, 128, 512)
                        if min(display.width, display.height) // factor >= 1
                    ]
                    if levels:
                        display.build_overviews(
                            levels, rasterio.enums.Resampling.nearest
                        )
        geod = Geod(ellps="WGS84")
        area_per_row = []
        transform = first.transform
        for row in range(first.height):
            west, north = transform * (0, row)
            east, south = transform * (1, row + 1)
            area_per_row.append(
                abs(
                    geod.polygon_area_perimeter(
                        [west, east, east, west], [north, north, south, south]
                    )[0]
                )
            )
        target_area = float(np.dot(target_per_row, area_per_row))
        valid_area = float(np.dot(valid_per_row, area_per_row))
        patch_count = patches.finish()
        statistics = {
            "area_ha": target_area / 10000,
            "patch_count": int(patch_count),
            "valid_area_km2": valid_area / 1000000,
            "coverage_percent": target_area / valid_area * 100 if valid_area else 0,
        }
        return {
            "statistics": statistics,
            "validPixelCount": int(valid_per_row.sum()),
            "targetPixelCount": int(target_per_row.sum()),
            "bounds": list(first.bounds),
            "grid": {
                "width": first.width,
                "height": first.height,
                "transform": list(first.transform)[:6],
                "crs": "EPSG:4326",
            },
            "method": "RF",
            "inputPeriods": [],
            "normalization": "输入16波段原值，三季节顺序拼接",
            "connectivity": 8,
            "processing": {
                "streaming": True,
                "blockSize": BLOCK_SIZE,
                "skippedInvalidBlocks": skipped,
                "concurrentTiles": CONCURRENT_TILES,
            },
        }
