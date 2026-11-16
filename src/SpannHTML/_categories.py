"""Categorical annotation encoding and CSV updates."""

from __future__ import annotations

import colorsys
import re

import numpy as np
import pandas as pd

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def normalize_color(value):
    """Return a six-digit hex color, or None for an unsupported value."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
        value = "#" + "".join(char * 2 for char in value[1:])
    if re.fullmatch(r"#[0-9a-fA-F]{8}", value):
        value = value[:7]
    return value.lower() if _HEX_COLOR.fullmatch(value) else None


def generate_colors(count):
    colors = []
    for index in range(count):
        hue = (0.08 + 0.618033988749895 * (index + 1)) % 1
        rgb = colorsys.hsv_to_rgb(hue, 0.62 + 0.05 * (index % 3), 0.82 + 0.12 * (index % 2))
        colors.append("#" + "".join(f"{round(channel * 255):02x}" for channel in rgb))
    return colors


def factorize_obs(series):
    """Encode labels without conflating missing values or colliding display names."""
    if isinstance(series.dtype, pd.CategoricalDtype):
        codes = series.cat.codes.to_numpy(dtype=np.int64, copy=True)
        values = series.cat.categories.tolist()
    else:
        codes, values = pd.factorize(series, sort=False, use_na_sentinel=True)
        values = values.tolist()
    has_missing = bool((codes < 0).any())
    names = [str(value) for value in values]
    if has_missing:
        codes[codes < 0] = len(names)
        names.append("<Missing>")
    reserved = set(names)
    used = set()
    labels = []
    for name in names:
        label = name
        suffix = 2
        if label in used:
            while True:
                label = f"{name} [{suffix}]"
                suffix += 1
                if label not in reserved and label not in used:
                    break
        used.add(label)
        labels.append(label)
    return np.asarray(codes, dtype=np.int64), labels, values, has_missing


def annotation_colors(stored, count, has_missing):
    colors = generate_colors(count)
    if isinstance(stored, (list, tuple, np.ndarray, pd.Series)):
        for index, color in enumerate(stored[: count - int(has_missing)]):
            colors[index] = normalize_color(color) or colors[index]
    if has_missing:
        colors[-1] = "#9e9e9e"
    return colors


def encode_annotation(series, stored_colors, indices):
    codes, names, _, has_missing = factorize_obs(series)
    colors = annotation_colors(stored_colors, len(names), has_missing)
    used, remapped = np.unique(codes[indices], return_inverse=True)
    categories = [
        {
            "name": names[index],
            "original_name": names[index],
            "color": colors[index],
            "missing": has_missing and index == len(names) - 1,
        }
        for index in used.tolist()
    ]
    return {"categories": categories, "category_ids": remapped.tolist()}


def update_annotation(series, edits, stored_colors):
    """Prepare one update and palette; leave the original Series untouched."""
    codes, labels, values, has_missing = factorize_obs(series)
    lookup = dict(zip(labels, values))
    colors = annotation_colors(stored_colors, len(labels), has_missing)
    color_by_label = dict(zip(labels, colors))
    targets = edits["edited_category"]
    if "category_missing" in edits:
        missing = edits["category_missing"].map(parse_bool)
    elif has_missing:
        missing = targets.eq(labels[-1])
    else:
        missing = pd.Series(False, index=edits.index)
    if "category_color" in edits:
        for label, group in edits.loc[~missing].groupby("edited_category", sort=False):
            palette = group["category_color"].map(normalize_color)
            if palette.isna().any() or palette.nunique() != 1:
                raise ValueError(f"Annotation color for {label!r} must be one valid hex color.")
            color_by_label[label] = palette.iloc[0]
    if "original_category" in edits:
        for target, group in edits.groupby("edited_category", sort=False):
            if target not in color_by_label:
                source = group["original_category"].value_counts().index[0]
                if source in color_by_label:
                    color_by_label[target] = color_by_label[source]

    # New text labels in a numeric annotation require a homogeneous string
    # categorical so the result can still be written to h5ad.
    new_text = any(label not in lookup for label in targets[~missing])
    stringify = new_text and any(not isinstance(value, str) for value in values)
    if stringify:
        original_values = [np.nan if code < 0 else labels[code] for code in codes]
        if has_missing:
            original_values = [
                np.nan if code == len(labels) - 1 else value
                for code, value in zip(codes, original_values)
            ]
        updated = pd.Series(original_values, index=series.index, dtype=object)
        replacements = targets.astype(object).mask(missing, np.nan)
        category_order = labels[: len(values)]
    else:
        updated = series.astype(object).copy()
        replacements = pd.Series(
            [
                np.nan if is_missing else lookup.get(label, label)
                for label, is_missing in zip(targets, missing)
            ],
            index=edits.index,
            dtype=object,
        )
        category_order = values
    updated.loc[edits["barcode"].tolist()] = replacements.to_numpy()
    unchanged = updated.eq(series) | (updated.isna() & series.isna())
    if bool(unchanged.all()):
        final = series.copy()
    else:
        present = pd.unique(updated.dropna()).tolist()
        order = [value for value in category_order if value in present]
        order.extend(value for value in present if value not in order)
        final = pd.Series(
            pd.Categorical(
                updated,
                categories=order,
                ordered=isinstance(series.dtype, pd.CategoricalDtype) and series.cat.ordered,
            ),
            index=series.index,
            name=series.name,
        )
    _, final_labels, _, final_missing = factorize_obs(final)
    fallback = generate_colors(len(final_labels))
    palette = [
        color_by_label.get(label, fallback[index]) for index, label in enumerate(final_labels)
    ]
    if final_missing:
        palette = palette[:-1]
    return final, np.asarray(palette, dtype=str)


def parse_bool(value):
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Expected a boolean value, received {value!r}.")
