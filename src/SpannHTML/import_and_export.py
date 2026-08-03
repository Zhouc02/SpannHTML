#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html
import json
from plotly.offline import get_plotlyjs

from .HTML_template import HTML_TEMPLATE
from .utils import *


def export_spatial_html(
    adata_or_path: Union[AnnData, PathLike],
    obs_key: str,
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

    adata = load_adata(adata_or_path)

    if obs_key not in adata.obs.columns:
        available = ", ".join(map(str, adata.obs.columns[:20]))
        suffix = " ..." if adata.obs.shape[1] > 20 else ""
        raise KeyError(
            f"adata.obs has no column {obs_key!r}, "
            f"May usable column: {available}{suffix}"
        )

    if spatial_key not in adata.obsm:
        available = ", ".join(map(str, adata.obsm.keys()))
        raise KeyError(
            f"adata.obsm has no key {spatial_key!r}, "
            f"May usable key: {available or 'None'}"
        )

    if not adata.obs_names.is_unique:
        raise ValueError(
            "adata.obs_names must be unique"
        )

    coordinates = np.asarray(adata.obsm[spatial_key])
    if coordinates.ndim != 2:
        raise ValueError(
            f"adata.obsm[{spatial_key!r}] must be two-dimensional matrix, "
            f"current shape={coordinates.shape}"
        )
    if x_col < 0 or y_col < 0:
        raise ValueError("x_col and y_col must be non-negative integers")
    if x_col == y_col:
        raise ValueError("x_col and y_col must indicate different spatial columns")
    if max(x_col, y_col) >= coordinates.shape[1]:
        raise IndexError(
            f"Spatial coordinates has only {coordinates.shape[1]} column, "
            f"could not read x_col={x_col}、y_col={y_col}"
        )
    if coordinates.shape[0] != adata.n_obs:
        raise ValueError(
            "Rows of spatial coordinates are not matched to adata.n_obs:"
            f"{coordinates.shape[0]} != {adata.n_obs}"
        )
    if point_size <= 0:
        raise ValueError("point_size must be greater than 0")
    if not 0.0 <= opacity <= 1.0:
        raise ValueError("opacity must be between 0 and 1")
    if max_points is not None and max_points <= 0:
        raise ValueError("max_points must be positive integers or None")

    x_values = np.asarray(coordinates[:, x_col], dtype=float)
    y_values = np.asarray(coordinates[:, y_col], dtype=float)
    finite_mask = np.isfinite(x_values) & np.isfinite(y_values)
    if not finite_mask.any():
        raise ValueError("No available finite X/Y coordinates in the spatial coordinates")
    transform_center_x = float(
        (np.min(x_values[finite_mask]) + np.max(x_values[finite_mask])) / 2.0
    )
    transform_center_y = float(
        (np.min(y_values[finite_mask]) + np.max(y_values[finite_mask])) / 2.0
    )

    category_ids, category_names, has_missing = factorize_obs(
        adata.obs[obs_key]
    )
    colors = extract_colors(
        adata,
        obs_key,
        category_names,
        has_missing,
    )
    barcodes = np.asarray(adata.obs_names.astype(str), dtype=object)

    retained_indices = np.flatnonzero(finite_mask)
    omitted_nonfinite = int((~finite_mask).sum())

    if max_points is not None and retained_indices.size > max_points:
        random = np.random.default_rng(random_seed)
        retained_indices = np.sort(
            random.choice(
                retained_indices,
                size=max_points,
                replace=False,
            )
        )

    x_values = x_values[retained_indices]
    y_values = y_values[retained_indices]
    category_ids = category_ids[retained_indices]
    barcodes = barcodes[retained_indices]

    used_category_ids = np.unique(category_ids)
    old_to_new = {
        int(old_id): new_id
        for new_id, old_id in enumerate(used_category_ids.tolist())
    }
    remapped_category_ids = np.asarray(
        [old_to_new[int(category_id)] for category_id in category_ids],
        dtype=np.int64,
    )

    categories = [
        {
            "id": new_id,
            "name": category_names[int(old_id)],
            "original_name": category_names[int(old_id)],
            "color": colors[int(old_id)],
        }
        for new_id, old_id in enumerate(used_category_ids.tolist())
    ]

    page_title = title or f"SpannHTML · {obs_key}"
    output_path = Path(output_html).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "title": page_title,
        "obs_key": obs_key,
        "spatial_key": spatial_key,
        "n_total": int(adata.n_obs),
        "n_rendered": int(retained_indices.size),
        "omitted_nonfinite": omitted_nonfinite,
        "sampled": bool(
            max_points is not None
            and int(finite_mask.sum()) > retained_indices.size
        ),
        "point_size": float(point_size),
        "opacity": float(opacity),
        "invert_y": bool(invert_y),
        "x_col": int(x_col),
        "y_col": int(y_col),
        "transform_center_x": transform_center_x,
        "transform_center_y": transform_center_y,
        "categories": categories,
        "points": {
            "x": x_values.tolist(),
            "y": y_values.tolist(),
            "barcodes": barcodes.tolist(),
            "category_ids": remapped_category_ids.tolist(),
        },
    }

    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    final_html = (
        HTML_TEMPLATE
        .replace("__PAGE_TITLE__", html.escape(page_title, quote=True))
        .replace("__PLOTLY_JS__", get_plotlyjs())
        .replace("__PAYLOAD_JSON__", payload_json)
    )

    output_path.write_text(final_html, encoding="utf-8")
    return output_path


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

    source_adata = load_adata(adata_or_path)
    adata = source_adata if inplace else source_adata.copy()

    if not adata.obs_names.is_unique:
        raise ValueError("adata.obs_names must be unique")

    csv_file = Path(csv_path).expanduser().resolve()
    if not csv_file.exists():
        raise FileNotFoundError(f"Could not found: {csv_file}")

    edits = pd.read_csv(
        csv_file,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )

    required = {barcode_column, category_column}
    missing_columns = required.difference(edits.columns)
    if missing_columns:
        raise ValueError(
            "Missing column"
            + ", ".join(sorted(missing_columns))
        )

    resolved_obs_key = resolve_csv_obs_key(edits, obs_key)
    if resolved_obs_key not in adata.obs.columns:
        raise KeyError(
            f"adata.obs has no column {resolved_obs_key!r}"
        )

    edits = edits.copy()
    edits[barcode_column] = edits[barcode_column].astype(str).str.strip()
    edits[category_column] = edits[category_column].astype(str).str.strip()

    if (edits[barcode_column] == "").any():
        raise ValueError("CSV has empty barcode")
    if (edits[category_column] == "").any():
        raise ValueError("CSV has empty edited_category")

    edits = deduplicate_edits(
        edits,
        barcode_column=barcode_column,
        category_column=category_column,
    )

    obs_name_set = set(map(str, adata.obs_names))
    missing_barcodes = [
        barcode
        for barcode in edits[barcode_column].tolist()
        if barcode not in obs_name_set
    ]

    if missing_barcodes and not allow_missing_barcodes:
        preview = ", ".join(missing_barcodes[:10])
        suffix = " ..." if len(missing_barcodes) > 10 else ""
        raise KeyError(
            f"Missing {len(missing_barcodes)} barcodes "
            f"and not exist in adata.obs_names: {preview}{suffix}"
        )

    if missing_barcodes:
        edits = edits[
            edits[barcode_column].isin(obs_name_set)
        ].copy()

    original_series = adata.obs[resolved_obs_key].copy()
    target_by_barcode = dict(
        zip(
            edits[barcode_column].tolist(),
            edits[category_column].tolist(),
        )
    )

    if isinstance(original_series.dtype, pd.CategoricalDtype):
        updated = original_series.copy()
        new_categories = [
            category
            for category in pd.unique(edits[category_column]).tolist()
            if category not in updated.cat.categories
        ]
        if new_categories:
            updated = updated.cat.add_categories(new_categories)

        barcodes_to_update = list(target_by_barcode)
        updated.loc[barcodes_to_update] = [
            target_by_barcode[barcode]
            for barcode in barcodes_to_update
        ]
        updated = updated.cat.remove_unused_categories()
    else:
        updated = original_series.astype(object).copy()
        for barcode, category in target_by_barcode.items():
            updated.loc[barcode] = category

        updated = updated.astype("category")

    adata.obs[resolved_obs_key] = updated
    refresh_obs_colors(
        adata,
        resolved_obs_key,
        original_series,
        edits,
        adata.obs[resolved_obs_key],
    )
    if apply_spatial_transform:
        apply_spatial_transform_from_csv(
            adata,
            edits,
            spatial_key=spatial_key,
        )
    return adata