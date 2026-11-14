# -*- coding: utf-8 -*-

"""
AGRS_semantic_segmentation
模型预测 v2 — 重构版
~~~~~~~~~~~~~~~~

主要改进:
- 双缓冲 + 多卡轮转推理流水线
- 废弃 DataParallel，采用单进程多卡模型副本并行推理
- 波段读取数跟随 band_num 配置（不再硬编码 3）
- 使用 logging 替代 print
- dataclass 配置、上下文管理器、类型注解等现代 Python 实践

用法:
通过 JSON 批量配置运行（推荐）:
    python predict_v2.py --config batch_predict_config.json
旧版单任务 YAML 仍兼容:
    python predict_v2.py config.yaml

code by wHy
Aerospace Information Research Institute, Chinese Academy of Sciences
wanghaoyu191@mails.ucas.ac.cn
"""

from __future__ import annotations

import os

import argparse
import copy
import dataclasses
import fnmatch
import gc
import hashlib
import json
import logging
import queue
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, NamedTuple, Sequence

# Windows 下先加载 PyTorch 的 Intel OpenMP 运行库，再加载其他二进制扩展。
import torch
import torch.nn as nn
from PIL import Image as _PILImage  # noqa: F401

import numpy as np

# ── 模型导入（保持原样，通过 globals() 按名称查找） ──────────────
from networks.UNet import UNet  # noqa: F401
from osgeo import gdal
from tqdm import tqdm

# ── 全局设置 ──────────────────────────────────────────────────────
# 无命令行参数时默认读取的配置文件路径（可手动修改）
DEFAULT_CONFIG_PATH = ""
# 旧变量保留兼容；新项目请使用 DEFAULT_CONFIG_PATH。
DEFAULT_YAML_CONFIG_PATH = ""

gdal.UseExceptions()

_GDAL_DTYPE_MAP: dict[str, int] = {
    "GDT_Byte": gdal.GDT_Byte,
    "GDT_UInt16": gdal.GDT_UInt16,
}

_NUMPY_DTYPE_MAP: dict[int, type] = {
    gdal.GDT_Byte: np.uint8,
    gdal.GDT_UInt16: np.uint16,
}

_GEOTIFF_CREATE_OPTIONS: list[str] = [
    "TILED=YES",
    "BLOCKXSIZE=1024",
    "BLOCKYSIZE=1024",
    "COMPRESS=ZSTD",
]

logger = logging.getLogger("predict_v2")


# ═══════════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════════


class NormStats(NamedTuple):
    """归一化统计量。"""

    mean: np.ndarray
    std: np.ndarray


class TileGrid(NamedTuple):
    """预计算的 tile 网格信息。"""

    margin: int
    step: int
    x_positions: list[int]
    y_positions: list[int]
    max_x: int
    max_y: int
    total_count: int


class TileTask(NamedTuple):
    """单个 tile 写回所需的元数据。"""

    xoff: int
    yoff: int
    src_y0: int
    src_y1: int
    src_x0: int
    src_x1: int


class ChunkTask(NamedTuple):
    """一批相邻 tiles 共享同一次 GDAL 读取的元数据。"""

    chunk_x: int
    chunk_y: int
    read_w: int
    read_h: int
    tiles: list[TileTask]


# ═══════════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════════

# YAML key -> dataclass field name 映射
_YAML_KEY_MAP: dict[str, str] = {
    "predictImgPath": "predict_img_path",
    "Img_type": "img_type",
    "num_class": "num_class",
    "model": "model",
    "model_path": "model_path",
    "output_path": "output_path",
    "band_num": "band_num",
    "label_norm": "label_norm",
    "target_size": "target_size",
    "overlap_rate": "overlap_rate",
    "batch_size": "batch_size",
    "amp_enable": "amp_enable",
    "prefetch_size": "prefetch_size",
    "flush_interval": "flush_interval",
    "read_chunk_size": "read_chunk_size",
    "ignore_bandnum": "ignore_bandnum",
    "img_data_type": "img_data_type",
    "mean": "mean",
    "std": "std",
    "gpu_ids": "gpu_ids",
    "class_values": "class_values",
}


@dataclass
class PredictConfig:
    """单个权重任务的预测配置。

    新增字段:
        mean / std:    模型固定归一化参数。
        gpu_ids:       指定使用的 GPU 编号列表，默认 None = 自动使用所有可用卡。
    """

    predict_img_path: str = ""
    img_type: str = "*.tif"
    num_class: int = 2
    model: str = ""
    model_path: str = ""
    output_path: str = ""
    band_num: int = 3
    label_norm: bool = True
    target_size: int = 256
    overlap_rate: float = 0.1
    batch_size: int = 32
    amp_enable: bool = True
    prefetch_size: int = 2
    flush_interval: int = 65536
    read_chunk_size: int = 4096
    ignore_bandnum: int = 0
    img_data_type: str = "GDT_Byte"

    # ── 新增 ──
    mean: list[float] | None = None
    std: list[float] | None = None
    gpu_ids: list[int] | None = None
    class_values: list[int] | None = None

    # ── 校验 ──

    def __post_init__(self) -> None:
        if self.num_class < 2:
            raise ValueError("num_class 必须大于等于 2")
        if self.band_num < 1:
            raise ValueError("band_num 必须大于等于 1")
        if self.batch_size < 1:
            raise ValueError("batch_size 必须大于等于 1")
        if self.target_size < 1:
            raise ValueError("target_size 必须大于等于 1")
        if self.read_chunk_size < self.target_size:
            raise ValueError("read_chunk_size 必须大于等于 target_size")
        # 要求 read_chunk_size 是 target_size 的整数倍，以避免分块碎片化并保持高吞吐。
        if self.read_chunk_size % self.target_size != 0:
            raise ValueError(
                "read_chunk_size 必须是 target_size 的整数倍，请调整配置文件中的 read_chunk_size"
            )
        if self.flush_interval < 1:
            raise ValueError("flush_interval 必须大于等于 1")
        if not (0 <= self.overlap_rate < 0.5):
            raise ValueError("overlap_rate 必须在 [0, 0.5) 范围内")
        if (self.mean is None) != (self.std is None):
            raise ValueError("mean 和 std 必须同时填写或同时省略")
        if not 0 <= self.ignore_bandnum <= self.band_num:
            raise ValueError("ignore_bandnum 必须在 [0, band_num] 范围内")
        if self.class_values is not None:
            if len(self.class_values) != self.num_class:
                raise ValueError("class_values 长度必须等于 num_class")
            if len(set(self.class_values)) != len(self.class_values):
                raise ValueError("class_values 不能重复")
            if min(self.class_values) < 0:
                raise ValueError("class_values 不能包含负数")
            dtype = np.dtype(self.numpy_dtype)
            if max(self.class_values) > np.iinfo(dtype).max:
                raise ValueError("class_values 超出 img_data_type 可表示范围")
        normalize_count = self.band_num - self.ignore_bandnum
        if self.mean is not None and len(self.mean) < normalize_count:
            raise ValueError("mean 长度小于需要归一化的波段数")
        if self.std is not None and len(self.std) < normalize_count:
            raise ValueError("std 长度小于需要归一化的波段数")

    # ── 属性 ──

    @property
    def gdal_data_type(self) -> int:
        """将字符串 img_data_type 解析为 GDAL 常量。"""
        if isinstance(self.img_data_type, int):
            return self.img_data_type
        dt = _GDAL_DTYPE_MAP.get(self.img_data_type)
        if dt is None:
            raise ValueError(f"不支持的 img_data_type: {self.img_data_type!r}")
        return dt

    @property
    def numpy_dtype(self) -> type:
        """对应的 numpy 数据类型。"""
        dt = _NUMPY_DTYPE_MAP.get(self.gdal_data_type)
        if dt is None:
            raise ValueError("不支持的 GDAL 数据类型，无法映射为 numpy dtype")
        return dt

    def resolve_model_class(self) -> type:
        """通过模型名称（字符串）查找模型类。"""
        cls = globals().get(self.model)
        if cls is None:
            raise ValueError(f"未知模型: {self.model!r}")
        return cls

    # ── 工厂方法 ──

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PredictConfig:
        """从字典构建配置，自动映射 YAML camelCase 键名。"""
        field_names = {f.name for f in dataclasses.fields(cls) if f.init}
        mapped: dict[str, Any] = {}
        for key, value in raw.items():
            target = _YAML_KEY_MAP.get(key, key)
            if target in field_names:
                mapped[target] = value
        return cls(**mapped)

    @classmethod
    def from_yaml(cls, config_path: Path) -> PredictConfig:
        """读取旧版单任务 YAML 配置。"""
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("读取YAML需要安装PyYAML: pip install pyyaml") from exc
        with config_path.open("r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream) or {}
        if not isinstance(loaded, dict):
            raise ValueError("YAML顶层必须是对象")
        return cls.from_dict(loaded)


@dataclass(frozen=True)
class PredictionJob:
    """批量推理中的一个权重任务。"""

    name: str
    config: PredictConfig

    @property
    def output_dir(self) -> Path:
        return Path(self.config.output_path)

    @property
    def completion_path(self) -> Path:
        return self.output_dir / f"{self.name}.completed.json"

    @property
    def log_path(self) -> Path:
        return self.output_dir / "logs" / f"{self.name}.log"


# ═══════════════════════════════════════════════════════════════════
#  归一化统计量
# ═══════════════════════════════════════════════════════════════════


def get_normalization_stats(config: PredictConfig) -> NormStats:
    """Read the fixed model normalization parameters."""
    if config.mean is None or config.std is None:
        raise ValueError("Inference requires fixed mean and std in model configuration")
    mean = np.asarray(config.mean, dtype=np.float32)
    std = np.asarray(config.std, dtype=np.float32)
    return NormStats(mean=mean, std=std)


# ═══════════════════════════════════════════════════════════════════
#  模型加载
# ═══════════════════════════════════════════════════════════════════


class ModelLoader:
    """加载模型权重，自动兼容 DataParallel 保存的 ``module.`` 前缀权重。"""

    @staticmethod
    def load(
        model_cls: type,
        num_classes: int,
        band_num: int,
        weight_path: str,
        device: torch.device | str = "cpu",
    ) -> nn.Module:
        """实例化模型 → 加载权重 → 移到 *device* → eval 模式。"""
        model = model_cls(num_classes=num_classes, band_num=band_num)

        state_dict = torch.load(weight_path, map_location="cpu", weights_only=True)

        # 兼容 DataParallel 保存的权重（key 带 'module.' 前缀）
        if any(k.startswith("module.") for k in state_dict):
            state_dict = OrderedDict(
                (k.removeprefix("module."), v) for k, v in state_dict.items()
            )

        model.load_state_dict(state_dict)
        model.to(device)
        model.eval()
        logger.info("模型已加载: device=%s, weights=%s", device, weight_path)
        return model


# ═══════════════════════════════════════════════════════════════════
#  GDAL I/O 上下文管理器
# ═══════════════════════════════════════════════════════════════════


class GeoTiffReader:
    """GeoTIFF 读取器（上下文管理器）。"""

    def __init__(self, path: str, band_num: int) -> None:
        self.path = path
        self.band_num = band_num
        self._dataset: gdal.Dataset | None = None
        self._band_list = list(range(1, band_num + 1))

    def __enter__(self) -> GeoTiffReader:
        self._dataset = gdal.Open(self.path, gdal.GA_ReadOnly)
        if self._dataset is None:
            raise IOError(f"无法打开影像: {self.path}")
        if self._dataset.RasterCount < self.band_num:
            raise ValueError(
                f"影像波段数({self._dataset.RasterCount}) 小于所需波段数({self.band_num}): {self.path}"
            )
        return self

    def __exit__(self, *exc: object) -> None:
        self._dataset = None

    @property
    def dataset(self) -> gdal.Dataset:
        assert self._dataset is not None, "GeoTiffReader 未进入上下文"
        return self._dataset

    @property
    def width(self) -> int:
        return self.dataset.RasterXSize

    @property
    def height(self) -> int:
        return self.dataset.RasterYSize

    @property
    def projection(self) -> str:
        return self.dataset.GetProjection()

    @property
    def geo_transform(self) -> tuple:
        return self.dataset.GetGeoTransform()

    def read_array(self, xoff: int, yoff: int, w: int, h: int) -> np.ndarray:
        """读取指定区域的多波段数组 (C, H, W)。"""
        arr = self.dataset.ReadAsArray(xoff, yoff, w, h, band_list=self._band_list)
        if arr is None:
            raise IOError(f"GDAL ReadAsArray 返回 None: ({xoff},{yoff},{w},{h})")
        return arr


class GeoTiffWriter:
    """单波段 GeoTIFF 写入器（上下文管理器），用于保存预测结果。"""

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        gdal_dtype: int,
        projection: str,
        geo_transform: tuple,
    ) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        driver = gdal.GetDriverByName("GTiff")
        self._dataset = driver.Create(
            path,
            width,
            height,
            1,
            gdal_dtype,
            options=_GEOTIFF_CREATE_OPTIONS,
        )
        if self._dataset is None:
            raise IOError(f"无法创建输出 GeoTIFF: {path}")
        # 类别 0 是有效的背景类别，不能标记成 NoData。
        self._dataset.SetGeoTransform(geo_transform)
        self._dataset.SetProjection(projection)
        self._band = self._dataset.GetRasterBand(1)

    def __enter__(self) -> GeoTiffWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        if self._dataset is not None:
            self._dataset.FlushCache()
            self._band = None
            self._dataset = None

    def write_array(self, data: np.ndarray, xoff: int, yoff: int) -> None:
        self._band.WriteArray(data, xoff, yoff)

    def flush(self) -> None:
        if self._dataset is not None:
            self._dataset.FlushCache()


# ═══════════════════════════════════════════════════════════════════
#  Tile 网格计算（纯函数，易于测试）
# ═══════════════════════════════════════════════════════════════════


def compute_tile_grid(
    width: int,
    height: int,
    tile_size: int,
    overlap_rate: float,
) -> TileGrid:
    """计算带重叠的 tile 位置网格。"""
    margin = int(tile_size * overlap_rate)
    step = int(tile_size * (1 - 2 * overlap_rate))
    if step <= 0:
        raise ValueError("无效的 overlap_rate：计算出的步长必须大于 0")

    max_x = width - tile_size
    max_y = height - tile_size

    x_positions = list(range(0, max_x + 1, step))
    y_positions = list(range(0, max_y + 1, step))
    if x_positions[-1] != max_x:
        x_positions.append(max_x)
    if y_positions[-1] != max_y:
        y_positions.append(max_y)

    return TileGrid(
        margin=margin,
        step=step,
        x_positions=x_positions,
        y_positions=y_positions,
        max_x=max_x,
        max_y=max_y,
        total_count=len(x_positions) * len(y_positions),
    )


def make_tile_task(
    xoff: int,
    yoff: int,
    tile_size: int,
    margin: int,
    max_x: int,
    max_y: int,
) -> TileTask:
    """计算单个 tile 的裁剪边界（overlap 边缘处理）。"""
    src_x0 = 0 if xoff == 0 else margin
    src_x1 = tile_size if xoff == max_x else tile_size - margin
    src_y0 = 0 if yoff == 0 else margin
    src_y1 = tile_size if yoff == max_y else tile_size - margin
    return TileTask(xoff, yoff, src_y0, src_y1, src_x0, src_x1)


def iter_chunk_tasks(
    grid: TileGrid,
    chunk_size: int,
    img_width: int,
    img_height: int,
    tile_size: int,
) -> Iterator[ChunkTask]:
    """按空间分块分组 tile，每块共享一次 GDAL 读取，减少 I/O 开销。"""
    cs = int(chunk_size)

    x_chunks: dict[int, list[int]] = {}
    y_chunks: dict[int, list[int]] = {}
    for xoff in grid.x_positions:
        x_chunks.setdefault((xoff // cs) * cs, []).append(xoff)
    for yoff in grid.y_positions:
        y_chunks.setdefault((yoff // cs) * cs, []).append(yoff)

    for chunk_y in sorted(y_chunks):
        y_list = y_chunks[chunk_y]
        max_yoff = y_list[-1]
        for chunk_x in sorted(x_chunks):
            x_list = x_chunks[chunk_x]
            max_xoff = x_list[-1]
            tiles = [
                make_tile_task(
                    xoff, yoff, tile_size, grid.margin, grid.max_x, grid.max_y
                )
                for xoff in x_list
                for yoff in y_list
            ]
            if not tiles:
                continue
            read_w = min((max_xoff + tile_size) - chunk_x, img_width - chunk_x)
            read_h = min((max_yoff + tile_size) - chunk_y, img_height - chunk_y)
            yield ChunkTask(chunk_x, chunk_y, read_w, read_h, tiles)


# ═══════════════════════════════════════════════════════════════════
#  多 GPU 推理引擎
# ═══════════════════════════════════════════════════════════════════


class MultiGPUPredictor:
    """在多张 GPU 上维护独立的模型副本，实现零额外开销的并行推理。

    单卡时行为与普通单 GPU 推理完全一致；多卡时各卡独立推理，
    通过 round-robin 分发 batch，配合各卡独立的 CUDA stream 实现
    计算 / 数据传输的 overlap。
    """

    def __init__(
        self,
        model: nn.Module,
        norm_stats: NormStats,
        band_num: int,
        ignore_bandnum: int = 0,
        gpu_ids: list[int] | None = None,
        class_values: list[int] | None = None,
    ) -> None:
        if gpu_ids is None:
            count = torch.cuda.device_count()
            gpu_ids = list(range(count)) if count > 0 else []
        if not gpu_ids:
            raise RuntimeError("没有可用的 CUDA GPU")

        self.gpu_ids = gpu_ids
        self.band_num = band_num
        self.num_gpus = len(gpu_ids)
        self._class_values = (
            np.asarray(class_values) if class_values is not None else None
        )
        self._devices = [torch.device(f"cuda:{gid}") for gid in gpu_ids]

        # 预处理归一化参数
        normalize_count = band_num - ignore_bandnum
        mean_np = np.zeros(band_num, dtype=np.float32)
        std_np = np.ones(band_num, dtype=np.float32)
        mean_np[:normalize_count] = norm_stats.mean[:normalize_count]
        std_np[:normalize_count] = norm_stats.std[:normalize_count]
        std_np[std_np == 0] = 1.0  # 避免除零；被忽略的末尾波段保持原值

        # 每卡: 模型副本 + 归一化 tensor + CUDA stream
        self._models: dict[int, nn.Module] = {}
        self._mean_tensors: dict[int, torch.Tensor] = {}
        self._std_tensors: dict[int, torch.Tensor] = {}
        self._streams: dict[int, torch.cuda.Stream] = {}  # type: ignore[type-arg]

        for idx, device in enumerate(self._devices):
            # 多卡时始终从 CPU 基准模型复制，避免从 GPU0 深拷贝造成瞬时显存峰值。
            m = (
                model.to(device)
                if self.num_gpus == 1
                else copy.deepcopy(model).to(device)
            )
            m.eval()
            dev_id = device.index
            self._models[dev_id] = m
            self._mean_tensors[dev_id] = torch.as_tensor(
                mean_np, dtype=torch.float32, device=device
            ).view(1, band_num, 1, 1)
            self._std_tensors[dev_id] = torch.as_tensor(
                std_np, dtype=torch.float32, device=device
            ).view(1, band_num, 1, 1)
            self._streams[dev_id] = torch.cuda.Stream(device=device)  # type: ignore[assignment]

        logger.info("推理引擎就绪: %d 张 GPU %s", self.num_gpus, self.gpu_ids)

    # ── 推理 ──

    @torch.inference_mode()
    def predict_batch(
        self,
        batch_tensor: torch.Tensor,
        device_idx: int,
        use_amp: bool,
        out_dtype: type,
    ) -> np.ndarray:
        """在指定 GPU 上执行一个 batch 的推理。"""
        device = self._devices[device_idx]
        dev_id = device.index
        ch = batch_tensor.shape[1]

        normalized = (
            batch_tensor - self._mean_tensors[dev_id][:, :ch]
        ) / self._std_tensors[dev_id][:, :ch]

        with torch.autocast(device_type="cuda", enabled=use_amp):
            logits = self._models[dev_id](normalized)

        prediction = torch.argmax(logits, dim=1).cpu().numpy()
        if self._class_values is not None:
            prediction = self._class_values[prediction]
        return prediction.astype(out_dtype, copy=False)

    # ── 异步数据传输 ──

    def enqueue_to_device(
        self,
        cpu_tensor: torch.Tensor,
        device_idx: int,
    ) -> torch.Tensor:
        """通过 CUDA stream 异步拷贝 pinned CPU tensor 到指定 GPU。"""
        device = self._devices[device_idx]
        stream = self._streams[device.index]
        if not cpu_tensor.is_pinned():
            cpu_tensor = cpu_tensor.pin_memory()
        with torch.cuda.stream(stream):
            return cpu_tensor.to(device, dtype=torch.float32, non_blocking=True)

    def get_stream(self, device_idx: int) -> torch.cuda.Stream:
        return self._streams[self._devices[device_idx].index]

    def get_device(self, device_idx: int) -> torch.device:
        return self._devices[device_idx]


# ═══════════════════════════════════════════════════════════════════
#  预测流水线
# ═══════════════════════════════════════════════════════════════════


class PredictionPipeline:
    """编排 producer-consumer 流水线，支持多卡并行推理。

    流水线结构::

        [GDAL 读取线程] ──pin_memory──▶ Queue ──▶ [主线程: batch 组装 → 多卡推理 → 写回]

    - 后台线程按 chunk 读取遥感影像并 pin_memory
    - 主线程消费 queue，双缓冲预取，round-robin 分发到各 GPU
    - 写回通过 GeoTiffWriter 写入 GeoTIFF
    """

    def __init__(
        self,
        predictor: MultiGPUPredictor,
        config: PredictConfig,
        overwrite: bool = False,
    ) -> None:
        self.predictor = predictor
        self.config = config
        self.overwrite = overwrite
        self._failed: list[tuple[str, str]] = []
        self.completed_count = 0
        self.skipped_count = 0

    @property
    def failed_images(self) -> list[tuple[str, str]]:
        return list(self._failed)

    def run(self, image_paths: Sequence[str]) -> None:
        """依次处理所有影像。"""
        for path in image_paths:
            self._process_image(path)

        if self._failed:
            logger.warning("失败影像: %d 张", len(self._failed))
            for img_path, reason in self._failed:
                logger.warning("  - %s (%s)", img_path, reason)

    # ── 单张影像 ──

    def _process_image(self, image_path: str) -> None:
        """处理单张影像的完整流程。"""
        cfg = self.config
        t0 = time.time()

        try:
            with GeoTiffReader(image_path, cfg.band_num) as reader:
                if reader.width < cfg.target_size or reader.height < cfg.target_size:
                    raise ValueError(
                        f"影像尺寸({reader.width}x{reader.height})小于 "
                        f"target_size({cfg.target_size})"
                    )

                out_name = Path(image_path).stem + ".tif"
                out_path = Path(cfg.output_path) / out_name
                if out_path.exists() and not self.overwrite:
                    self.skipped_count += 1
                    logger.info("输出已存在，跳过: %s", out_path)
                    return

                partial_path = out_path.with_name(f"{out_path.stem}.partial.tif")
                partial_path.unlink(missing_ok=True)

                with GeoTiffWriter(
                    str(partial_path),
                    reader.width,
                    reader.height,
                    cfg.gdal_data_type,
                    reader.projection,
                    reader.geo_transform,
                ) as writer:
                    self._run_pipeline(reader, writer, image_path)

                partial_path.replace(out_path)

        except Exception as exc:
            if "partial_path" in locals():
                partial_path.unlink(missing_ok=True)
            self._failed.append((image_path, str(exc)))
            logger.warning("跳过 %s: %s", image_path, exc)
            return

        self.completed_count += 1
        logger.info("预测完成 %s  耗时 %.1fs", Path(image_path).name, time.time() - t0)

    # ── 核心流水线 ──

    def _run_pipeline(
        self,
        reader: GeoTiffReader,
        writer: GeoTiffWriter,
        image_path: str,
    ) -> None:
        """Producer-consumer 核心流水线。"""
        cfg = self.config

        grid = compute_tile_grid(
            reader.width,
            reader.height,
            cfg.target_size,
            cfg.overlap_rate,
        )
        chunk_iter = iter_chunk_tasks(
            grid,
            cfg.read_chunk_size,
            reader.width,
            reader.height,
            cfg.target_size,
        )

        maxsize = cfg.prefetch_size if cfg.prefetch_size > 0 else 0
        task_queue: queue.Queue = queue.Queue(maxsize=maxsize)
        sentinel = object()
        producer_error: list[Exception] = []

        # ── producer 线程 ──
        def producer() -> None:
            try:
                for chunk in chunk_iter:
                    img_block = reader.read_array(
                        chunk.chunk_x,
                        chunk.chunk_y,
                        chunk.read_w,
                        chunk.read_h,
                    )
                    tensor = torch.from_numpy(
                        np.ascontiguousarray(img_block)
                    ).pin_memory()
                    task_queue.put((chunk, tensor), block=True)
            except Exception as ex:
                producer_error.append(ex)
            finally:
                task_queue.put(sentinel, block=True)

        thread = threading.Thread(target=producer, daemon=True)
        thread.start()

        # ── consumer 循环 ──
        pbar = tqdm(
            total=grid.total_count,
            desc=f"预测 {Path(image_path).name}",
            unit="tiles",
            dynamic_ncols=True,
            mininterval=0.1,
        )

        write_count = 0
        iter_count = 0
        gpu_cursor = 0

        try:
            while True:
                item = task_queue.get(block=True)
                if item is sentinel:
                    break
                chunk, chunk_tensor = item
                write_count, iter_count, gpu_cursor = self._process_chunk(
                    chunk,
                    chunk_tensor,
                    writer,
                    pbar,
                    write_count,
                    iter_count,
                    gpu_cursor,
                )
                del chunk_tensor  # 尽早释放 CPU 内存
        finally:
            pbar.close()

        thread.join()
        if producer_error:
            raise producer_error[0]
        writer.flush()

    # ── 单个 chunk 处理 ──

    def _process_chunk(
        self,
        chunk: ChunkTask,
        chunk_tensor: torch.Tensor,
        writer: GeoTiffWriter,
        pbar: tqdm,
        write_count: int,
        iter_count: int,
        gpu_cursor: int,
    ) -> tuple[int, int, int]:
        """处理一个 chunk: 切片 tile → batch 组装 → GPU 推理 → 写回。

        采用双缓冲策略：当前 batch 在某张卡上推理时，下一 batch
        已经在另一张卡上异步传输，实现 compute / transfer overlap。
        """
        cfg = self.config
        target_size = cfg.target_size
        batch_size = cfg.batch_size
        num_gpus = self.predictor.num_gpus

        # 从 chunk 中切出各 tile 的 tensor
        prepared: list[tuple[TileTask, torch.Tensor]] = []
        for tile in chunk.tiles:
            local_x = tile.xoff - chunk.chunk_x
            local_y = tile.yoff - chunk.chunk_y
            tile_tensor = chunk_tensor[
                :, local_y : local_y + target_size, local_x : local_x + target_size
            ]
            prepared.append((tile, tile_tensor))

        total_tiles = len(prepared)
        idx = 0

        # 双缓冲状态
        next_selected: list[TileTask] = []
        next_batch_gpu: torch.Tensor | None = None
        next_device_idx: int = 0

        while idx < total_tiles or next_batch_gpu is not None:
            # ── 首次进入时加载第一个 batch ──
            if next_batch_gpu is None:
                end = min(idx + batch_size, total_tiles)
                batch_slice = prepared[idx:end]
                idx = end
                dev = gpu_cursor % num_gpus
                gpu_cursor += 1
                next_selected = [t for t, _ in batch_slice]
                cpu_batch = torch.stack([s for _, s in batch_slice])
                if not cpu_batch.is_pinned():
                    cpu_batch = cpu_batch.pin_memory()
                next_batch_gpu = self.predictor.enqueue_to_device(cpu_batch, dev)
                next_device_idx = dev

            # 交换: current ← next
            current_selected = next_selected
            current_batch = next_batch_gpu
            current_dev = next_device_idx

            # ── 预取下一个 batch（到另一张卡） ──
            if idx < total_tiles:
                end = min(idx + batch_size, total_tiles)
                batch_slice = prepared[idx:end]
                idx = end
                dev = gpu_cursor % num_gpus
                gpu_cursor += 1
                next_selected = [t for t, _ in batch_slice]
                cpu_batch = torch.stack([s for _, s in batch_slice])
                if not cpu_batch.is_pinned():
                    cpu_batch = cpu_batch.pin_memory()
                next_batch_gpu = self.predictor.enqueue_to_device(cpu_batch, dev)
                next_device_idx = dev
            else:
                next_selected = []
                next_batch_gpu = None
                next_device_idx = 0

            # ── 等待当前 batch 传输完成 → 推理 ──
            stream = self.predictor.get_stream(current_dev)
            device = self.predictor.get_device(current_dev)
            torch.cuda.current_stream(device).wait_stream(stream)

            results = self.predictor.predict_batch(
                current_batch,
                current_dev,
                cfg.amp_enable,
                cfg.numpy_dtype,
            )

            # ── 写回 ──
            for result, tile in zip(results, current_selected):
                patch = result[tile.src_y0 : tile.src_y1, tile.src_x0 : tile.src_x1]
                writer.write_array(
                    patch, tile.xoff + tile.src_x0, tile.yoff + tile.src_y0
                )
                write_count += 1
                pbar.update(1)
                if write_count % cfg.flush_interval == 0:
                    writer.flush()

            iter_count += 1
            if iter_count % 20 == 0:
                pbar.set_postfix(bs=batch_size, GPUs=num_gpus)

        return write_count, iter_count, gpu_cursor % num_gpus


# ═══════════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════════


def setup_logging() -> None:
    """配置日志：时间戳 + 级别 + 消息。"""
    if any(getattr(handler, "_agrs_console", False) for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler._agrs_console = True  # type: ignore[attr-defined]
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def collect_image_paths(directory: str, pattern: str) -> list[str]:
    """收集匹配指定通配符的影像文件路径。"""
    if not Path(directory).is_dir():
        raise FileNotFoundError(f"输入影像目录不存在: {directory}")
    names = fnmatch.filter(os.listdir(directory), pattern)
    paths = [
        os.path.join(directory, n)
        for n in sorted(names)
        if Path(directory, n).is_file()
    ]
    if not paths:
        raise FileNotFoundError(f"未找到匹配 {pattern!r} 的影像: {directory}")
    logger.info("找到 %d 张待预测影像", len(paths))
    return paths


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析批量 JSON 或兼容的单任务 YAML 参数。"""
    parser = argparse.ArgumentParser(description="AGRS 多权重批量语义分割推理")
    parser.add_argument(
        "legacy_config", nargs="?", help="兼容旧用法的 YAML/JSON 配置路径"
    )
    parser.add_argument("--config", help="批量 JSON 配置路径（推荐）")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="只运行指定任务")
    parser.add_argument(
        "--gpu-ids", nargs="+", type=int, help="覆盖全部任务的 GPU 编号"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="覆盖已有输出并重新推理"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="仅校验配置、权重和首张影像"
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="任一任务失败后立即停止"
    )
    return parser.parse_args(argv)


def _absolute_path(value: Any, base_dir: Path) -> str:
    """将配置中的相对路径按配置文件所在目录解析。"""
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve())


def _canonical_config(raw: dict[str, Any]) -> dict[str, Any]:
    return {_YAML_KEY_MAP.get(key, key): value for key, value in raw.items()}


def _resolve_config_paths(raw: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = _canonical_config(raw)
    for key in ("predict_img_path", "model_path", "output_path"):
        if resolved.get(key):
            resolved[key] = _absolute_path(resolved[key], base_dir)
    return resolved


def load_prediction_jobs(
    args: argparse.Namespace,
) -> tuple[list[PredictionJob], Path, Path]:
    """加载批量 JSON 或旧版 YAML，返回任务、摘要路径和配置路径。"""
    selected_path = (
        args.config
        or args.legacy_config
        or DEFAULT_CONFIG_PATH
        or DEFAULT_YAML_CONFIG_PATH
    )
    if not selected_path:
        raise ValueError("请通过 --config 指定批量 JSON，或传入旧版 YAML 路径")

    config_path = Path(selected_path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    base_dir = config_path.parent
    jobs: list[PredictionJob] = []

    if config_path.suffix.lower() in {".yaml", ".yml"}:
        config_raw = _resolve_config_paths(
            dataclasses.asdict(PredictConfig.from_yaml(config_path)), base_dir
        )
        if args.gpu_ids is not None:
            config_raw["gpu_ids"] = args.gpu_ids
        jobs.append(
            PredictionJob(config_path.stem, PredictConfig.from_dict(config_raw))
        )
        summary_path = base_dir / "batch_prediction_summary.json"
    else:
        with config_path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if not isinstance(document, dict):
            raise ValueError("JSON 顶层必须是对象")
        defaults = document.get("defaults", {})
        raw_jobs = document.get("jobs")
        if not isinstance(defaults, dict):
            raise ValueError("defaults 必须是对象")
        if not isinstance(raw_jobs, list) or not raw_jobs:
            raise ValueError("jobs 必须是非空数组")

        output_root_value = document.get("output_root")
        output_root = (
            Path(_absolute_path(output_root_value, base_dir))
            if output_root_value
            else None
        )
        names: set[str] = set()
        for index, raw_job in enumerate(raw_jobs, start=1):
            if not isinstance(raw_job, dict):
                raise ValueError(f"jobs[{index - 1}] 必须是对象")
            if raw_job.get("enabled", True) is False:
                continue
            name = str(raw_job.get("name", "")).strip()
            if not name:
                raise ValueError(f"jobs[{index - 1}] 缺少非空 name")
            if name in names:
                raise ValueError(f"任务名称重复: {name}")
            if any(char in name for char in '<>:"/\\|?*'):
                raise ValueError(f"任务名称含 Windows 路径非法字符: {name!r}")
            names.add(name)

            merged = dict(defaults)
            merged.update(raw_job)
            if not merged.get("output_path"):
                if output_root is None:
                    raise ValueError(
                        f"任务 {name!r} 未配置 output_path，且缺少 output_root"
                    )
                merged["output_path"] = str(output_root / name)
            if args.gpu_ids is not None:
                merged["gpu_ids"] = args.gpu_ids
            merged = _resolve_config_paths(merged, base_dir)
            jobs.append(PredictionJob(name, PredictConfig.from_dict(merged)))

        summary_value = document.get("summary_path")
        summary_path = (
            Path(_absolute_path(summary_value, base_dir))
            if summary_value
            else base_dir / "batch_prediction_summary.json"
        )

    if args.only:
        requested = set(args.only)
        known = {job.name for job in jobs}
        unknown = requested - known
        if unknown:
            raise ValueError(f"--only 包含未知任务: {sorted(unknown)}")
        jobs = [job for job in jobs if job.name in requested]
    if not jobs:
        raise ValueError("没有可运行的推理任务")
    output_owners: dict[Path, str] = {}
    for job in jobs:
        output_dir = job.output_dir.resolve()
        if output_dir in output_owners:
            raise ValueError(
                f"任务 {output_owners[output_dir]!r} 与 {job.name!r} 的输出目录重复: "
                f"{output_dir}"
            )
        output_owners[output_dir] = job.name
    return jobs, summary_path, config_path


def validate_job(job: PredictionJob) -> list[str]:
    """执行不占用模型显存的任务前置校验，并返回影像列表。"""
    cfg = job.config
    if not torch.cuda.is_available():
        raise RuntimeError("当前 PyTorch 未检测到可用 CUDA GPU")
    device_count = torch.cuda.device_count()
    if cfg.gpu_ids is not None:
        invalid = [idx for idx in cfg.gpu_ids if idx < 0 or idx >= device_count]
        if invalid:
            raise ValueError(
                f"任务 {job.name!r} 的 gpu_ids 无效: {invalid}，GPU数={device_count}"
            )
    if not Path(cfg.model_path).is_file():
        raise FileNotFoundError(f"任务 {job.name!r} 权重不存在: {cfg.model_path}")
    cfg.resolve_model_class()
    if cfg.mean is None or cfg.std is None:
        raise ValueError("Fixed mean/std are required for inference")
    input_dir = Path(cfg.predict_img_path).resolve()
    if input_dir == job.output_dir.resolve():
        raise ValueError(f"任务 {job.name!r} 的输入目录与输出目录不能相同")

    image_paths = collect_image_paths(cfg.predict_img_path, cfg.img_type)
    with GeoTiffReader(image_paths[0], cfg.band_num) as reader:
        if reader.width < cfg.target_size or reader.height < cfg.target_size:
            raise ValueError(
                f"首张影像尺寸 {reader.width}x{reader.height} 小于 target_size={cfg.target_size}"
            )
    return image_paths


def _write_json(path: Path, content: Any) -> None:
    """以临时文件替换方式写 JSON，避免中断留下半份摘要。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _add_job_file_handler(job: PredictionJob) -> logging.FileHandler:
    job.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(job.log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return handler


def _job_fingerprint(job: PredictionJob, image_paths: Sequence[str]) -> str:
    """根据配置、权重和输入文件元数据生成轻量任务指纹。"""
    input_files = []
    for value in image_paths:
        path = Path(value)
        stat = path.stat()
        input_files.append(
            {
                "path": str(path.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    weight_path = Path(job.config.model_path)
    weight_stat = weight_path.stat()
    payload = {
        "config": dataclasses.asdict(job.config),
        "weight": {"size": weight_stat.st_size, "mtime_ns": weight_stat.st_mtime_ns},
        "inputs": input_files,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_prediction_job(
    job: PredictionJob,
    image_paths: Sequence[str],
    overwrite: bool,
) -> dict[str, Any]:
    """运行一个权重任务，结束时彻底释放其 CPU/GPU 模型资源。"""
    cfg = job.config
    expected_outputs = [
        job.output_dir / f"{Path(path).stem}.tif" for path in image_paths
    ]
    fingerprint = _job_fingerprint(job, image_paths)
    if not overwrite and job.completion_path.is_file():
        try:
            marker = json.loads(job.completion_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"完成标记损坏，请加 --overwrite 重跑: {job.completion_path}"
            ) from exc
        if marker.get("fingerprint") != fingerprint:
            raise RuntimeError(
                f"任务 {job.name!r} 的配置、权重或输入已变化；请加 --overwrite 重跑"
            )
        if all(path.is_file() for path in expected_outputs):
            logger.info("任务 %s 已完整完成，跳过", job.name)
            return {
                "name": job.name,
                "status": "skipped_existing",
                "model_path": cfg.model_path,
                "output_path": str(job.output_dir),
                "image_count": len(image_paths),
            }

    job.output_dir.mkdir(parents=True, exist_ok=True)
    job.completion_path.unlink(missing_ok=True)
    file_handler = _add_job_file_handler(job)
    started = time.time()
    model: nn.Module | None = None
    predictor: MultiGPUPredictor | None = None
    pipeline: PredictionPipeline | None = None
    try:
        logger.info("=" * 72)
        logger.info("开始任务 %s，权重: %s", job.name, cfg.model_path)
        norm_stats = get_normalization_stats(cfg)
        model = ModelLoader.load(
            cfg.resolve_model_class(),
            num_classes=cfg.num_class,
            band_num=cfg.band_num,
            weight_path=cfg.model_path,
        )
        predictor = MultiGPUPredictor(
            model,
            norm_stats,
            cfg.band_num,
            cfg.ignore_bandnum,
            cfg.gpu_ids,
            cfg.class_values,
        )
        pipeline = PredictionPipeline(predictor, cfg, overwrite=overwrite)
        pipeline.run(image_paths)

        failures = [
            {"image": image, "error": error} for image, error in pipeline.failed_images
        ]
        result: dict[str, Any] = {
            "name": job.name,
            "status": "completed" if not failures else "partial_failed",
            "model_path": cfg.model_path,
            "output_path": str(job.output_dir),
            "image_count": len(image_paths),
            "completed_images": pipeline.completed_count,
            "skipped_images": pipeline.skipped_count,
            "failed_images": failures,
            "elapsed_seconds": round(time.time() - started, 3),
        }
        if not failures:
            marker = {
                "name": job.name,
                "model_path": cfg.model_path,
                "image_count": len(image_paths),
                "fingerprint": fingerprint,
                "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _write_json(job.completion_path, marker)
            logger.info("任务 %s 完成，耗时 %.1fs", job.name, result["elapsed_seconds"])
        else:
            logger.error("任务 %s 有 %d 张影像失败", job.name, len(failures))
        return result
    finally:
        logger.removeHandler(file_handler)
        file_handler.close()
        pipeline = None
        predictor = None
        model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def main(argv: Sequence[str] | None = None) -> int:
    """批量推理主入口。"""
    setup_logging()
    args = parse_args(argv)
    try:
        jobs, summary_path, config_path = load_prediction_jobs(args)
    except Exception as exc:
        logger.error("配置加载失败: %s", exc)
        return 2

    validated: list[tuple[PredictionJob, list[str]]] = []
    results: list[dict[str, Any]] = []
    logger.info("加载配置: %s", config_path)
    for job in jobs:
        try:
            image_paths = validate_job(job)
            validated.append((job, image_paths))
            logger.info(
                "校验通过: %-20s 影像=%d 输出=%s",
                job.name,
                len(image_paths),
                job.output_dir,
            )
        except Exception as exc:
            logger.error("任务 %s 校验失败: %s", job.name, exc)
            results.append(
                {
                    "name": job.name,
                    "status": "validation_failed",
                    "model_path": job.config.model_path,
                    "output_path": str(job.output_dir),
                    "error": repr(exc),
                }
            )
            if args.fail_fast:
                break

    if args.dry_run:
        logger.info(
            "dry-run 完成：通过=%d，失败=%d，未加载模型", len(validated), len(results)
        )
        return 1 if results else 0

    if results:
        _write_json(summary_path, results)
    if args.fail_fast and results:
        logger.info("批量推理已停止，摘要: %s", summary_path)
        return 1

    for job, image_paths in validated:
        try:
            result = run_prediction_job(job, image_paths, args.overwrite)
        except Exception as exc:
            logger.exception("任务 %s 失败", job.name)
            result = {
                "name": job.name,
                "status": "failed",
                "model_path": job.config.model_path,
                "output_path": str(job.output_dir),
                "error": repr(exc),
            }
        results.append(result)
        _write_json(summary_path, results)
        if args.fail_fast and result["status"] in {"failed", "partial_failed"}:
            break

    logger.info("批量推理结束，摘要: %s", summary_path)
    failed_statuses = {"validation_failed", "failed", "partial_failed"}
    return 1 if any(item["status"] in failed_statuses for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
