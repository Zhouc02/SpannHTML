# SpannHTML

[![Python Versions](https://img.shields.io/pypi/pyversions/SpannHTML.svg)](https://pypi.org/project/SpannHTML/) [![PyPI version](https://img.shields.io/pypi/v/SpannHTML.svg)](https://pypi.org/project/SpannHTML/) [![PyPI Downloads](https://static.pepy.tech/personalized-badge/SpannHTML?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/SpannHTML) [![License](https://img.shields.io/pypi/l/SpannHTML.svg)](https://pypi.org/project/SpannHTML/)

SpannHTML exports AnnData spatial annotations into a single offline HTML file.
Inspect annotations, correct spots, rename and recolor categories, and adjust
spatial orientation in a browser. Export CSV edits and apply them in Python.

## Installation

```bash
pip install SpannHTML
```

## Export and switch annotations

```python
from SpannHTML import export_spatial_html

export_spatial_html(adata, obs_key="cluster", output_html="spatial_viewer.html")
```

A string `obs_key` selects the initial field and includes other categorical,
string, and boolean obs columns in the **Annotation** selector. Numeric fields
are included only when explicitly requested. All fields are categorical displays.

Pass a list to choose exactly which fields are embedded, and in which order:

```python
export_spatial_html(
    adata,
    obs_key=["cluster", "cell_type", "leiden"],
    output_html="spatial_viewer.html",
)
```

Use `obs_key=["cluster"]` to include only one field. An `.h5ad` path can replace
the AnnData object.

Observation identifiers and obs column names must be unique. Non-finite x/y rows
are omitted and counted in the sidebar. `max_points` optionally samples a
reproducible subset; CSV exports contain only displayed spots.

## Browser editing

1. Choose an annotation.
2. Click a spot, choose a category, and click **Apply to spot**.
3. Rename, recolor, show, or hide categories.
4. Switch fields to continue editing. Each field retains its own edits, names,
   colors, and visibility within the session.
5. Export the current annotation or all annotations as CSV.

## CSV schema and import

Each row represents one **(barcode, obs_key)** pair. An all-annotation CSV repeats
barcodes across different fields; these are separate annotation values.

| Column              | Meaning                                                 |
| ------------------- | ------------------------------------------------------- |
| `barcode`           | Observation identifier                                  |
| `obs_key`           | Annotation field                                        |
| `original_category` | Label before editing                                    |
| `edited_category`   | Label after editing                                     |
| `category_changed`  | Whether the assigned value or non-missing label changed |
| `category_color`    | Final category color                                    |
| `category_missing`  | Whether the assigned value represents missing data      |

The redundant 1.1.0 `changed` column is removed; old CSVs
containing it remain readable. Original and edited labels intentionally describe
different states, even for unchanged rows.

Spatial columns retain original and displayed x/y, the spatial key, axis columns,
rotation, flips, center, and source coordinate identifier. Original and displayed
coordinate pairs describe different states. The transform applies to the complete
AnnData coordinate array, including spots omitted from a sampled display.

```python
from SpannHTML import apply_edit

# Apply every field named in the CSV.
edited = apply_edit(adata, "spatial_annotations_edits.csv")

# Apply only one field.
edited = apply_edit(adata, "spatial_annotations_edits.csv", obs_key="cell_type")

# Update annotations and colors without changing spatial coordinates.
edited = apply_edit(
    adata, "cluster_spatial_edits.csv", apply_spatial_transform=False
)
edited.write_h5ad("sample_edited.h5ad")
```

## AnnData auditing

```python
from SpannHTML import audit_adata

report = audit_adata(
    adata,
    max_matrix_sample=200_000,
    max_rows_for_axis_checks=4_000,
    random_state=0,
    include_pass=True,
)
report.print()
```

Checks cover matrices, identifiers, obs/var metadata, layers/raw, embeddings,
graphs, analysis metadata, spatial coordinates, tissue-image metadata, and palettes.
Findings contain a check ID, severity (`ERROR`, `WARN`, `INFO`, `PASS`),
evidence, and a suggested action. The audit is read-only. Matrix-state labels are
sample-based estimates.
