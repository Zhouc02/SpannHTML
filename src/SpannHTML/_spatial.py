"""Spatial transforms shared by HTML export and CSV import."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from ._categories import parse_bool


def spatial_fingerprint(coordinates, barcodes, x_col, y_col):
    xy = np.array(coordinates[:, [x_col, y_col]], dtype="<f8", order="C")
    xy[np.isnan(xy)] = np.nan
    xy[xy == 0] = 0
    digest = hashlib.sha256(xy.tobytes())
    digest.update(json.dumps(list(map(str, barcodes)), ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def transform_xy(xy, settings, *, inverse=False):
    """Apply rotation followed by screen-aligned flips around a fixed center."""
    center = np.array([settings["center_x"], settings["center_y"]])
    turns = settings["rotation_clockwise_deg"] // 90
    rotation = np.array([[0.0, -1.0], [1.0, 0.0]])
    if not settings["invert_y"]:
        rotation = rotation.T
    matrix = np.linalg.matrix_power(rotation, turns)
    flips = np.diag(
        [
            -1 if settings["mirror_left_right"] else 1,
            -1 if settings["mirror_up_down"] else 1,
        ]
    )
    matrix = flips @ matrix
    if inverse:
        matrix = matrix.T
    return (np.asarray(xy, dtype=float) - center) @ matrix.T + center


def csv_value(edits, column):
    if column not in edits:
        raise ValueError(f"Spatial transform CSV is missing column {column!r}.")
    values = edits[column].unique()
    if len(values) != 1 or values[0] == "":
        raise ValueError(f"CSV column {column!r} must contain one consistent, non-empty value.")
    return values[0]


def prepare_spatial_edit(adata, edits, spatial_key=None):
    """Validate and prepare a transform before any changes are committed."""
    if "spatial_transformed" not in edits or edits.empty:
        return None
    enabled = parse_bool(csv_value(edits, "spatial_transformed"))
    if not enabled and "coordinate_id" not in edits:
        return None
    key = spatial_key or csv_value(edits, "spatial_key")
    if key not in adata.obsm:
        raise KeyError(f"Spatial coordinate key {key!r} was not found in adata.obsm.")
    settings = {
        "x_col": int(csv_value(edits, "x_col")),
        "y_col": int(csv_value(edits, "y_col")),
        "rotation_clockwise_deg": int(csv_value(edits, "rotation_clockwise_deg")),
        "mirror_left_right": parse_bool(csv_value(edits, "mirror_left_right")),
        "mirror_up_down": parse_bool(csv_value(edits, "mirror_up_down")),
        "center_x": float(csv_value(edits, "transform_center_x")),
        "center_y": float(csv_value(edits, "transform_center_y")),
        "invert_y": parse_bool(csv_value(edits, "transform_invert_y")),
    }
    x_col, y_col = settings["x_col"], settings["y_col"]
    coordinates = np.array(adata.obsm[key], dtype=float, copy=True)
    if (
        coordinates.ndim != 2
        or x_col < 0
        or y_col < 0
        or x_col == y_col
        or max(x_col, y_col) >= coordinates.shape[1]
    ):
        raise ValueError(
            "CSV x_col and y_col must identify two different spatial coordinate columns."
        )
    if settings["rotation_clockwise_deg"] not in {0, 90, 180, 270}:
        raise ValueError("Spatial rotation must be 0, 90, 180, or 270 degrees.")
    if not np.isfinite([settings["center_x"], settings["center_y"]]).all():
        raise ValueError("Spatial transform center must contain finite coordinates.")
    source_id = csv_value(edits, "coordinate_id") if "coordinate_id" in edits else None
    current_id = spatial_fingerprint(coordinates, adata.obs_names, x_col, y_col)
    if not enabled and current_id == source_id:
        return None
    previous = adata.uns.get(f"{key}_html_transform", {})
    if source_id and current_id != source_id:
        if previous.get("source_id") != source_id or previous.get("result_id") != current_id:
            raise ValueError(
                "Spatial coordinates differ from the source used to export this HTML. "
                "Apply the CSV to that source object or disable apply_spatial_transform."
            )
        if all(previous.get(name) == value for name, value in settings.items()):
            return None
        coordinates[:, [x_col, y_col]] = transform_xy(
            coordinates[:, [x_col, y_col]], previous, inverse=True
        )
    coordinates[:, [x_col, y_col]] = transform_xy(coordinates[:, [x_col, y_col]], settings)
    if source_id:
        settings.update(
            source_id=source_id,
            result_id=spatial_fingerprint(coordinates, adata.obs_names, x_col, y_col),
        )
    return key, coordinates, settings
