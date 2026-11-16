from __future__ import annotations

import csv
import html
import json
import operator
import re
from pathlib import Path
from typing import Optional, Sequence, Union

import numpy as np
import pandas as pd
from anndata import AnnData, read_h5ad
from plotly.offline import get_plotlyjs

from ._categories import encode_annotation, update_annotation
from ._spatial import prepare_spatial_edit, spatial_fingerprint

PathLike = Union[str, Path]


def _load_adata(adata_or_path):
    if isinstance(adata_or_path, AnnData):
        return adata_or_path
    path = Path(adata_or_path).expanduser().resolve()
    if path.suffix.lower() != ".h5ad":
        raise ValueError(f"Expected an AnnData object or an .h5ad file, received {path.name!r}.")
    return read_h5ad(path)


def _annotation_keys(obs, obs_key):
    if not obs.columns.is_unique:
        raise ValueError(
            "adata.obs column names must be unique before exporting or applying edits."
        )
    if isinstance(obs_key, str):
        keys = [obs_key]
        keys.extend(
            key
            for key in obs
            if key != obs_key
            and isinstance(key, str)
            and (
                isinstance(obs[key].dtype, pd.CategoricalDtype)
                or pd.api.types.is_object_dtype(obs[key])
                or pd.api.types.is_string_dtype(obs[key])
                or pd.api.types.is_bool_dtype(obs[key])
            )
        )
    else:
        keys = list(obs_key)
        if not keys or any(not isinstance(key, str) for key in keys):
            raise ValueError(
                "obs_key must be a column name or a non-empty sequence of column names."
            )
        keys = list(dict.fromkeys(keys))
    missing = [key for key in keys if key not in obs]
    if missing:
        raise KeyError(f"Annotation columns not found in adata.obs: {missing}.")
    return keys


def _index(value, name, minimum=0):
    try:
        number = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if isinstance(value, (bool, np.bool_)) or number < minimum:
        raise ValueError(f"{name} must be an integer greater than or equal to {minimum}.")
    return number


def export_spatial_html(
    adata_or_path: Union[AnnData, PathLike],
    obs_key: Union[str, Sequence[str]],
    output_html: PathLike = "spatial_viewer.html",
    *,
    spatial_key: str = "spatial",
    x_col: int = 0,
    y_col: int = 1,
    point_size: float = 6.0,
    opacity: float = 0.85,
    invert_y: bool = False,
    title: Optional[str] = None,
    max_points: Optional[int] = None,
    random_seed: int = 0,
) -> Path:
    """Create an offline spatial annotation viewer.

    A string ``obs_key`` selects the initial annotation and includes other
    categorical, string, and boolean obs columns. A sequence includes exactly
    those columns, in order. Each annotation keeps its own edits and palette.
    """
    adata = _load_adata(adata_or_path)
    keys = _annotation_keys(adata.obs, obs_key)
    if not adata.obs_names.is_unique:
        raise ValueError(
            "adata.obs_names must be unique; barcodes identify spots during CSV import."
        )
    if spatial_key not in adata.obsm:
        raise KeyError(f"Spatial coordinate key {spatial_key!r} was not found in adata.obsm.")
    x_col, y_col = _index(x_col, "x_col"), _index(y_col, "y_col")
    coordinates = np.asarray(adata.obsm[spatial_key])
    if (
        coordinates.ndim != 2
        or coordinates.shape[0] != adata.n_obs
        or x_col == y_col
        or max(x_col, y_col) >= coordinates.shape[1]
    ):
        raise ValueError(
            "Spatial coordinates must have one row per observation; "
            "x_col and y_col must identify two different columns."
        )
    if not np.isfinite(point_size) or point_size <= 0:
        raise ValueError("point_size must be a finite number greater than zero.")
    if not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("opacity must be a finite number between 0 and 1.")
    if max_points is not None:
        max_points = _index(max_points, "max_points", minimum=1)
    xy = np.asarray(coordinates[:, [x_col, y_col]], dtype=float)
    finite = np.isfinite(xy).all(axis=1)
    indices = np.flatnonzero(finite)
    if not len(indices):
        raise ValueError("No observations have finite x/y coordinates to display.")
    center = xy[indices].min(axis=0) / 2 + xy[indices].max(axis=0) / 2
    sampled = max_points is not None and len(indices) > max_points
    if sampled:
        indices = np.sort(
            np.random.default_rng(random_seed).choice(indices, size=max_points, replace=False)
        )
    annotations = {
        key: encode_annotation(adata.obs[key], adata.uns.get(f"{key}_colors"), indices)
        for key in keys
    }
    payload = {
        "title": title if title is not None else f"SpannHTML · {keys[0]}",
        "obs_key": keys[0],
        "annotation_keys": keys,
        "annotations": annotations,
        "spatial_key": spatial_key,
        "n_total": int(adata.n_obs),
        "n_rendered": len(indices),
        "omitted_nonfinite": int((~finite).sum()),
        "sampled": sampled,
        "point_size": float(point_size),
        "opacity": float(opacity),
        "invert_y": bool(invert_y),
        "x_col": x_col,
        "y_col": y_col,
        "transform_center_x": float(center[0]),
        "transform_center_y": float(center[1]),
        "coordinate_id": spatial_fingerprint(coordinates, adata.obs_names, x_col, y_col),
        "points": {
            "x": xy[indices, 0].tolist(),
            "y": xy[indices, 1].tolist(),
            "barcodes": adata.obs_names[indices].astype(str).tolist(),
        },
    }
    payload_json = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).replace("<", "\\u003c")
    static = Path(__file__).with_name("_static")
    replacements = {
        "PAGE_TITLE": html.escape(payload["title"], quote=True),
        "PLOTLY_JS": get_plotlyjs(),
        "PAYLOAD_JSON": payload_json,
        "STYLE": (static / "viewer.css").read_text(encoding="utf-8"),
        "SCRIPT": (static / "viewer.js").read_text(encoding="utf-8"),
    }
    page = re.sub(
        r"__(PAGE_TITLE|PLOTLY_JS|PAYLOAD_JSON|STYLE|SCRIPT)__",
        lambda match: replacements[match.group(1)],
        (static / "viewer.html").read_text(encoding="utf-8"),
    )
    output_path = Path(output_html).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


def _read_edits(csv_path, barcode_column, category_column):
    path = Path(csv_path).expanduser().resolve()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    if not header or len(header) != len(set(header)):
        raise ValueError("Edit CSV must have a non-empty header with unique column names.")
    if barcode_column == category_column:
        raise ValueError("barcode_column and category_column must name different columns.")
    required = {barcode_column, category_column}
    if not required.issubset(header):
        raise ValueError(
            f"Edit CSV is missing required columns: {sorted(required.difference(header))}."
        )
    edits = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for column in required:
        if edits[column].str.strip().eq("").any() and (
            column == barcode_column or "category_missing" not in edits
        ):
            raise ValueError(f"Edit CSV column {column!r} contains empty values.")
    # Normalize custom column names once; downstream helpers share one schema.
    edits[["barcode", "edited_category"]] = edits[[barcode_column, category_column]].to_numpy()
    return edits


def apply_edit(
    adata_or_path: Union[AnnData, PathLike],
    csv_path: PathLike,
    *,
    obs_key: Optional[str] = None,
    barcode_column: str = "barcode",
    category_column: str = "edited_category",
    allow_missing_barcodes: bool = False,
    apply_spatial_transform: bool = True,
    spatial_key: Optional[str] = None,
    inplace: bool = False,
) -> AnnData:
    """Apply current-annotation, multi-annotation, or legacy 1.1.0 edit CSVs.

    With ``obs_key=None``, all annotations named in the CSV are updated.
    Otherwise only that field is selected. Validation completes before an
    in-place update is committed. Spatial transforms are applied once.
    """
    source = _load_adata(adata_or_path)
    if not source.obs_names.is_unique or not source.obs.columns.is_unique:
        raise ValueError(
            "adata.obs_names and adata.obs column names must be unique before applying edits."
        )
    edits = _read_edits(csv_path, barcode_column, category_column)
    if "obs_key" not in edits:
        if obs_key is None:
            raise ValueError("Specify obs_key when the CSV does not contain an obs_key column.")
        edits["obs_key"] = obs_key
    elif edits["obs_key"].eq("").any():
        raise ValueError("Edit CSV contains empty obs_key values.")
    elif obs_key is not None:
        keys = edits["obs_key"].unique()
        if obs_key in keys:
            edits = edits.loc[edits["obs_key"].eq(obs_key)].copy()
        elif len(keys) == 1:
            # Keep the legacy ability to apply one annotation to another column.
            edits = edits.copy()
            edits["obs_key"] = obs_key
        else:
            raise KeyError(f"Annotation {obs_key!r} was not found in the edit CSV.")
    keys = list(pd.unique(edits["obs_key"]))
    if not keys:
        raise ValueError("Edit CSV contains no annotation rows to apply.")
    absent = [key for key in keys if key not in source.obs]
    if absent:
        raise KeyError(f"Annotation columns not found in adata.obs: {absent}.")
    unknown = ~edits["barcode"].isin(source.obs_names)
    if unknown.any() and not allow_missing_barcodes:
        examples = edits.loc[unknown, "barcode"].unique()[:10].tolist()
        raise KeyError(f"CSV barcodes were not found in adata.obs_names: {examples}.")
    spatial = prepare_spatial_edit(source, edits, spatial_key) if apply_spatial_transform else None
    edits = edits.loc[~unknown]
    updates = {}
    for key, group in edits.groupby("obs_key", sort=False):
        duplicate = group.duplicated("barcode", keep=False)
        compared = ["edited_category"] + [
            name for name in ("category_missing", "category_color") if name in group
        ]
        if duplicate.any() and (
            group.loc[duplicate].groupby("barcode")[compared].nunique().gt(1).any().any()
        ):
            raise ValueError(f"Edit CSV contains conflicting rows for the same barcode in {key!r}.")
        group = group.drop_duplicates("barcode", keep="last")
        updates[key] = update_annotation(source.obs[key], group, source.uns.get(f"{key}_colors"))
    adata = source if inplace else source.to_memory() if source.isbacked else source.copy()
    for key, (series, colors) in updates.items():
        adata.obs[key] = series
        adata.uns[f"{key}_colors"] = colors
    if spatial is not None:
        key, coordinates, settings = spatial
        adata.obsm[key] = coordinates
        adata.uns[f"{key}_html_transform"] = settings
    return adata
