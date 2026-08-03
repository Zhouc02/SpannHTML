#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import colorsys
import re
from pathlib import Path
from typing import Any, Optional, Union
import numpy as np
import pandas as pd
from anndata import AnnData, read_h5ad


PathLike = Union[str, Path]
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
__version__ = "1.0.0"

def _normalize_hex_color(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _HEX_RE.match(value):
        return None
    if len(value) == 4:
        return "#" + "".join(char * 2 for char in value[1:])
    return value[:7]


def _generate_colors(n: int) -> list[str]:
    if n <= 0:
        return []

    golden_ratio = 0.618033988749895
    hue = 0.08
    colors: list[str] = []

    for i in range(n):
        hue = (hue + golden_ratio) % 1.0
        saturation = 0.62 + 0.10 * ((i % 3) / 2.0)
        value = 0.82 + 0.12 * (i % 2)
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
        colors.append(
            f"#{round(red * 255):02x}"
            f"{round(green * 255):02x}"
            f"{round(blue * 255):02x}"
        )

    return colors


def _make_unique_labels(labels: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []

    for label in labels:
        number = seen.get(label, 0) + 1
        seen[label] = number
        result.append(label if number == 1 else f"{label} [{number}]")

    return result


def factorize_obs(series: pd.Series) -> tuple[np.ndarray, list[str], bool]:
    has_missing = bool(series.isna().any())

    if isinstance(series.dtype, pd.CategoricalDtype):
        codes = series.cat.codes.to_numpy(dtype=np.int64, copy=True)
        labels = [str(value) for value in series.cat.categories.tolist()]
    else:
        codes, unique_values = pd.factorize(
            series,
            sort=False,
            use_na_sentinel=True,
        )
        codes = codes.astype(np.int64, copy=False)
        labels = [str(value) for value in unique_values.tolist()]

    labels = _make_unique_labels(labels)

    if has_missing:
        missing_code = len(labels)
        codes[codes < 0] = missing_code
        labels.append("<Missing>")

    return codes, labels, has_missing


def extract_colors(
    adata: AnnData,
    obs_key: str,
    labels: list[str],
    has_missing: bool,
) -> list[str]:
    generated = _generate_colors(len(labels))
    stored = adata.uns.get(f"{obs_key}_colors")

    if stored is None:
        if has_missing and generated:
            generated[-1] = "#9e9e9e"
        return generated

    try:
        stored_colors = list(stored)
    except TypeError:
        stored_colors = []

    nonmissing_count = len(labels) - int(has_missing)
    colors: list[str] = []

    for index in range(nonmissing_count):
        stored_color = (
            _normalize_hex_color(stored_colors[index])
            if index < len(stored_colors)
            else None
        )
        colors.append(stored_color or generated[index])

    if has_missing:
        colors.append("#9e9e9e")

    return colors


def load_adata(adata_or_path: Union[AnnData, PathLike]) -> AnnData:
    if isinstance(adata_or_path, AnnData):
        return adata_or_path

    path = Path(adata_or_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Could not found AnnData file: {path}")
    if path.suffix.lower() != ".h5ad":
        raise ValueError(f"Support .h5ad file only: {path.name}")

    return read_h5ad(path)




def resolve_csv_obs_key(
    edits: pd.DataFrame,
    explicit_obs_key: Optional[str],
) -> str:
    if explicit_obs_key:
        return explicit_obs_key

    if "obs_key" not in edits.columns:
        raise ValueError(
            "Not specified obs_key, and no obs_key column in CSV file"
        )

    values = [
        value
        for value in edits["obs_key"].astype(str).str.strip().unique()
        if value
    ]
    if len(values) != 1:
        raise ValueError(
            "The obs_key column in the CSV must contain only one non-empty value, "
            f"currently detected: {values}"
        )
    return values[0]


def deduplicate_edits(
    edits: pd.DataFrame,
    barcode_column: str,
    category_column: str,
) -> pd.DataFrame:
    duplicated = edits[edits.duplicated(barcode_column, keep=False)]
    if duplicated.empty:
        return edits

    conflicts = (
        duplicated.groupby(barcode_column, sort=False)[category_column]
        .nunique(dropna=False)
    )
    conflict_barcodes = conflicts[conflicts > 1].index.tolist()
    if conflict_barcodes:
        preview = ", ".join(map(str, conflict_barcodes[:10]))
        suffix = " ..." if len(conflict_barcodes) > 10 else ""
        raise ValueError(
            "Multiple different target categories correspond to the same barcode in the CSV:"
            f"{preview}{suffix}"
        )

    return edits.drop_duplicates(barcode_column, keep="last")


def refresh_obs_colors(
    adata: AnnData,
    obs_key: str,
    original_series: pd.Series,
    edits: pd.DataFrame,
    final_series: pd.Series,
) -> None:

    if not isinstance(final_series.dtype, pd.CategoricalDtype):
        return

    final_categories = [str(value) for value in final_series.cat.categories]
    generated = _generate_colors(len(final_categories))

    original_labels: list[str]
    if isinstance(original_series.dtype, pd.CategoricalDtype):
        original_labels = [
            str(value) for value in original_series.cat.categories
        ]
    else:
        original_labels = [
            str(value)
            for value in pd.unique(original_series.dropna()).tolist()
        ]

    stored = adata.uns.get(f"{obs_key}_colors")
    original_color_map: dict[str, str] = {}
    if stored is not None:
        try:
            stored_list = list(stored)
        except TypeError:
            stored_list = []

        for index, label in enumerate(original_labels):
            if index >= len(stored_list):
                break
            color = _normalize_hex_color(stored_list[index])
            if color:
                original_color_map[label] = color

    source_by_target: dict[str, str] = {}
    if "original_category" in edits.columns:
        pairs = edits[["original_category", "edited_category"]].copy()
        pairs["original_category"] = pairs["original_category"].astype(str)
        pairs["edited_category"] = pairs["edited_category"].astype(str)
        for target, group in pairs.groupby("edited_category", sort=False):
            counts = group["original_category"].value_counts()
            if not counts.empty:
                source_by_target[str(target)] = str(counts.index[0])

    final_colors: list[str] = []
    for index, label in enumerate(final_categories):
        if label in original_color_map:
            final_colors.append(original_color_map[label])
            continue

        source = source_by_target.get(label)
        if source and source in original_color_map:
            final_colors.append(original_color_map[source])
            continue

        final_colors.append(generated[index])

    adata.uns[f"{obs_key}_colors"] = np.asarray(final_colors, dtype=object)


def _single_csv_value(
    edits: pd.DataFrame,
    column: str,
    *,
    required: bool = True,
) -> Optional[str]:
    if column not in edits.columns:
        if required:
            raise ValueError(f"Missing spatial transform column: {column!r}")
        return None

    values = [
        value
        for value in edits[column].astype(str).str.strip().unique().tolist()
        if value != ""
    ]
    if not values:
        if required:
            raise ValueError(f"Column {column!r} is empty")
        return None
    if len(values) != 1:
        raise ValueError(
            f"Column {column!r} has to be consistent across all rows, but the current values are: {values}"
        )
    return values[0]


def _parse_csv_bool(value: str, column: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Column {column!r} are not valid bool values: {value!r}")


def _transform_spatial_arrays(
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    center_x: float,
    center_y: float,
    rotation_clockwise_deg: int,
    mirror_left_right: bool,
    mirror_up_down: bool,
    invert_y: bool,
) -> tuple[np.ndarray, np.ndarray]:
    dx = np.asarray(x_values, dtype=float) - center_x
    dy = np.asarray(y_values, dtype=float) - center_y

    if rotation_clockwise_deg == 0:
        rotated_x, rotated_y = dx, dy
    elif rotation_clockwise_deg == 90:
        if invert_y:
            rotated_x, rotated_y = -dy, dx
        else:
            rotated_x, rotated_y = dy, -dx
    elif rotation_clockwise_deg == 180:
        rotated_x, rotated_y = -dx, -dy
    elif rotation_clockwise_deg == 270:
        if invert_y:
            rotated_x, rotated_y = dy, -dx
        else:
            rotated_x, rotated_y = -dy, dx
    else:
        raise ValueError(
            "rotation_clockwise_deg only support 0、90、180 or 270"
        )

    transformed_x = center_x + rotated_x
    transformed_y = center_y + rotated_y
    if mirror_left_right:
        transformed_x = 2.0 * center_x - transformed_x
    if mirror_up_down:
        transformed_y = 2.0 * center_y - transformed_y
    return transformed_x, transformed_y


def apply_spatial_transform_from_csv(
    adata: AnnData,
    edits: pd.DataFrame,
    *,
    spatial_key: Optional[str] = None,
) -> bool:
    if "spatial_transformed" not in edits.columns:
        return False

    transformed = _parse_csv_bool(
        _single_csv_value(edits, "spatial_transformed") or "false",
        "spatial_transformed",
    )
    if not transformed:
        return False

    resolved_spatial_key = spatial_key or _single_csv_value(edits, "spatial_key")
    if resolved_spatial_key is None or resolved_spatial_key not in adata.obsm:
        raise KeyError(
            f"adata.obsm has no spatial key: {resolved_spatial_key!r}"
        )

    x_col = int(_single_csv_value(edits, "x_col") or 0)
    y_col = int(_single_csv_value(edits, "y_col") or 1)
    rotation = int(_single_csv_value(edits, "rotation_clockwise_deg") or 0)
    mirror_left_right = _parse_csv_bool(
        _single_csv_value(edits, "mirror_left_right") or "false",
        "mirror_left_right",
    )
    mirror_up_down = _parse_csv_bool(
        _single_csv_value(edits, "mirror_up_down") or "false",
        "mirror_up_down",
    )
    center_x = float(_single_csv_value(edits, "transform_center_x") or 0.0)
    center_y = float(_single_csv_value(edits, "transform_center_y") or 0.0)
    invert_y = _parse_csv_bool(
        _single_csv_value(edits, "transform_invert_y") or "true",
        "transform_invert_y",
    )

    if x_col < 0 or y_col < 0 or x_col == y_col:
        raise ValueError("x_col and y_col must be non-negative integers")
    coordinates = np.asarray(
        adata.obsm[resolved_spatial_key],
        dtype=float,
    ).copy()
    if coordinates.ndim != 2 or max(x_col, y_col) >= coordinates.shape[1]:
        raise ValueError(
            f"adata.obsm[{resolved_spatial_key!r}] shape={coordinates.shape}, "
            f"could not use x_col={x_col}, y_col={y_col}"
        )

    transformed_x, transformed_y = _transform_spatial_arrays(
        coordinates[:, x_col],
        coordinates[:, y_col],
        center_x=center_x,
        center_y=center_y,
        rotation_clockwise_deg=rotation,
        mirror_left_right=mirror_left_right,
        mirror_up_down=mirror_up_down,
        invert_y=invert_y,
    )
    coordinates[:, x_col] = transformed_x
    coordinates[:, y_col] = transformed_y
    adata.obsm[resolved_spatial_key] = coordinates
    adata.uns[f"{resolved_spatial_key}_html_transform"] = {
        "rotation_clockwise_deg": rotation,
        "mirror_left_right": mirror_left_right,
        "mirror_up_down": mirror_up_down,
        "center_x": center_x,
        "center_y": center_y,
        "invert_y": invert_y,
        "x_col": x_col,
        "y_col": y_col,
    }
    return True


def _default_edited_h5ad_path(input_path: PathLike) -> Path:
    path = Path(input_path).expanduser().resolve()
    return path.with_name(f"{path.stem}.edited.h5ad")
