# SpannHTML

**SpannHTML** is a Python tool for exporting spatial omics annotations stored in an `AnnData` object into a standalone interactive HTML file.

The generated HTML can be opened directly in a browser without a Python environment, web server, or internet connection.

You can download `example_for_spatial_viewer.html` to experience its features.

## Features

* Read spatial coordinates from `adata.obsm["spatial"]`
* Visualize a categorical column from `adata.obs`
* Show, hide, rename, and recolor categories
* Select an individual spatial spot and change its category
* Search and highlight a spot by barcode
* Zoom and pan in the browser
* Rotate the complete spatial layout clockwise
* Mirror the spatial layout horizontally or vertically
* Adjust spot size and opacity
* Export the current view as PNG
* Export edited categories and spatial transformation settings as CSV
* Write the exported CSV back into an `AnnData` object
* Generate a fully self-contained and offline HTML file

## Quick start

```python
pip install SpannHTML

from SpannHTML import export_spatial_html
export_spatial_html(adata, obs_key="cluster", output_html="spatial_viewer.html")
```

A file path can also be passed directly:

```python
from SpannHTML import export_spatial_html
export_spatial_html("sample.h5ad", obs_key="cell_type", output_html="spatial_viewer.html")
```

## Optional parameters

```python
export_spatial_html(
    adata,
    obs_key="cluster",
    output_html="spatial_viewer.html",
    spatial_key="spatial",
    x_col=0,
    y_col=1,
    point_size=6,
    opacity=0.85,
    invert_y=False,
    max_points=None,
    random_seed=0,
)
```

Note that the exported CSV will only contain spots included in the HTML.

## Edit spatial annotations

In the generated HTML:

1. Click a spatial spot.
2. Select a target category.
3. Click **Apply to selected spot**.
4. Click **Export category CSV** when editing is complete.

The exported CSV contains fields such as:

```text
barcode
obs_key
original_category
edited_category
category_changed
original_x
original_y
x
y
rotation_clockwise_deg
mirror_left_right
mirror_up_down
```

## Write edited results back to AnnData

```python
from SpannHTML import apply_edit
edited_adata = apply_edit(adata, "cluster_spatial_edits.csv", obs_key="cluster")
```

The exported spatial rotation and mirror settings are applied to the corresponding columns in `adata.obsm["spatial"]`.

To update categories without modifying spatial coordinates:

```python
edited_adata = apply_edit(
    adata,
    "cluster_spatial_edits.csv",
    obs_key="cluster",
    apply_spatial_transform=False
)
```

## Notes

* Category renaming inside the HTML changes the displayed and exported category name.
* Browser edits do not directly modify the original `.h5ad` file.
* Refreshing the HTML restores its initial state.
* The HTML includes Plotly.js and all spatial coordinates, so file size increases with the number of spots.
* `adata.obs_names` must be unique because barcodes are used for spot lookup and CSV write-back.

