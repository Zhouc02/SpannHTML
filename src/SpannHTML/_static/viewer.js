"use strict";

const payload = JSON.parse(document.getElementById("payload").textContent);
const annotationStates = new Map(payload.annotation_keys.map(key => {
  const annotation = payload.annotations[key];
  return [key, {
    categories: annotation.categories.map(category => ({ ...category, visible: true })),
    pointCategory: annotation.category_ids.slice(),
    originalPointCategory: annotation.category_ids.slice()
  }];
}));
let activeKey = payload.obs_key;
let { categories, pointCategory } = annotationStates.get(activeKey);
const annotationSelect = document.getElementById("annotationSelect");

// Keep Plotly operations ordered when annotations or controls change quickly.
let plotQueue = Promise.resolve();
const plotly = Object.fromEntries(
  ["newPlot", "react", "restyle", "relayout", "downloadImage"].map(method => [
    method, (...args) => {
      const update = plotQueue.then(() => Plotly[method](...args));
      plotQueue = update.catch(error => {
        setStatus("The plot could not be updated. Export your edits before reloading this page.", true);
        console.error("SpannHTML plot update failed:", error);
      });
      return update;
    }
  ])
);
const originalPointX = payload.points.x.slice();
const originalPointY = payload.points.y.slice();
let pointX = originalPointX.slice();
let pointY = originalPointY.slice();
const barcodes = payload.points.barcodes;
const spatialTransform = {
  rotationClockwiseDeg: 0,
  mirrorLeftRight: false,
  mirrorUpDown: false
};
const transformCenterX = Number(payload.transform_center_x);
const transformCenterY = Number(payload.transform_center_y);


const plot = document.getElementById("plot");
const categorySelect = document.getElementById("categorySelect");
const pointCategorySelect = document.getElementById("pointCategorySelect");
const nameInput = document.getElementById("nameInput");
const colorInput = document.getElementById("colorInput");
const categoryCount = document.getElementById("categoryCount");
const originalNameHint = document.getElementById("originalNameHint");
const selectionSummary = document.getElementById("selectionSummary");
const statusBox = document.getElementById("status");
const sizeRange = document.getElementById("sizeRange");
const sizeNumber = document.getElementById("sizeNumber");
const opacityRange = document.getElementById("opacityRange");
const opacityNumber = document.getElementById("opacityNumber");
const findModal = document.getElementById("findModal");
const barcodeInput = document.getElementById("barcodeInput");
const applyPointCategoryButton = document.getElementById("applyPointCategoryButton");
const clearSelectionButton = document.getElementById("clearSelectionButton");
const transformSummary = document.getElementById("transformSummary");

let selectedPointId = null;
const selectedIds = () => selectedPointId === null ? [] : [selectedPointId];
let categoryPointIds = [];
let eventsRegistered = false;

const barcodeToPointId = new Map();
const lowercaseBarcodeToIds = new Map();
let globalXMin = Infinity;
let globalXMax = -Infinity;
let globalYMin = Infinity;
let globalYMax = -Infinity;

function updateGlobalBounds() {
  globalXMin = Infinity;
  globalXMax = -Infinity;
  globalYMin = Infinity;
  globalYMax = -Infinity;
  pointX.forEach(value => {
    globalXMin = Math.min(globalXMin, value);
    globalXMax = Math.max(globalXMax, value);
  });
  pointY.forEach(value => {
    globalYMin = Math.min(globalYMin, value);
    globalYMax = Math.max(globalYMax, value);
  });
}

updateGlobalBounds();
barcodes.forEach((barcode, pointId) => {
  barcodeToPointId.set(String(barcode), pointId);
  const lower = String(barcode).toLocaleLowerCase();
  const values = lowercaseBarcodeToIds.get(lower) || [];
  values.push(pointId);
  lowercaseBarcodeToIds.set(lower, values);
});

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.className = isError ? "status error" : "status";
}

function selectedCategoryId() {
  return Number(categorySelect.value || 0);
}

function categoryCounts() {
  const counts = Array(categories.length).fill(0);
  pointCategory.forEach(categoryId => {
    if (Number.isInteger(categoryId) && counts[categoryId] !== undefined) {
      counts[categoryId] += 1;
    }
  });
  return counts;
}

function rebuildCategoryPointIds() {
  categoryPointIds = Array.from({ length: categories.length }, () => []);
  pointCategory.forEach((categoryId, pointId) => {
    if (categoryPointIds[categoryId]) {
      categoryPointIds[categoryId].push(pointId);
    }
  });
}

function updateOriginalNameHint() {
  if (!categories.length) return;
  const category = categories[selectedCategoryId()];
  const candidate = nameInput.value.trim();
  const changed = candidate && candidate !== category.original_name;
  if (changed) {
    originalNameHint.textContent = `Original name: ${category.original_name}`;
    originalNameHint.style.display = "block";
  } else {
    originalNameHint.textContent = "";
    originalNameHint.style.display = "none";
  }
}

function syncCategoryControls() {
  if (!categories.length) return;
  const categoryId = selectedCategoryId();
  const category = categories[categoryId];
  const counts = categoryCounts();
  nameInput.value = category.name;
  colorInput.value = category.color;
  categoryCount.textContent = counts[categoryId].toLocaleString();
  updateOriginalNameHint();
}

function rebuildCategorySelectors(keepCategoryId = 0) {
  const counts = categoryCounts();
  categorySelect.replaceChildren();
  pointCategorySelect.replaceChildren();

  categories.forEach((category, categoryId) => {
    const text = `${category.name} (${counts[categoryId]})`;

    const categoryOption = document.createElement("option");
    categoryOption.value = String(categoryId);
    categoryOption.textContent = text;
    categorySelect.appendChild(categoryOption);

    const pointOption = document.createElement("option");
    pointOption.value = String(categoryId);
    pointOption.textContent = text;
    pointCategorySelect.appendChild(pointOption);
  });

  const safeId = Math.min(
    Math.max(Number(keepCategoryId) || 0, 0),
    Math.max(categories.length - 1, 0)
  );
  categorySelect.value = String(safeId);
  syncCategoryControls();
}

function updateSelectionUI() {
  const ids = selectedIds();
  const disabled = ids.length === 0;
  applyPointCategoryButton.disabled = disabled;
  clearSelectionButton.disabled = disabled;

  if (!ids.length) {
    selectionSummary.textContent = "No spatial spot selected";
    return;
  }

  const pointId = ids[0];
  const categoryId = pointCategory[pointId];
  selectionSummary.textContent =
    `Barcode: ${barcodes[pointId]}
Current category: ${categories[categoryId].name}`;
  pointCategorySelect.value = String(categoryId);
  categorySelect.value = String(categoryId);
  syncCategoryControls();
}

function highlightTrace() {
  const ids = selectedIds();
  return {
    type: "scattergl",
    mode: "markers",
    name: "Selected point",
    x: ids.map(pointId => pointX[pointId]),
    y: ids.map(pointId => pointY[pointId]),
    customdata: ids.map(pointId => [pointId, barcodes[pointId]]),
    marker: {
      color: "#111827",
      line: { color: "#111827", width: 2.5 },
      size: Math.max(Number(sizeNumber.value) + 8, 13),
      symbol: "circle-open",
      opacity: 1
    },
    hovertemplate:
      "<b>Selected point</b><br>barcode: %{customdata[1]}<br>" +
      "x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>",
    showlegend: false,
    selectable: false
  };
}

function buildTraces() {
  rebuildCategoryPointIds();
  const size = Number(sizeNumber.value);
  const opacity = Number(opacityNumber.value);

  const dataTraces = categories.map((category, categoryId) => {
    const ids = categoryPointIds[categoryId];
    return {
      type: "scattergl",
      mode: "markers",
      name: escapeHtml(category.name),
      x: ids.map(pointId => pointX[pointId]),
      y: ids.map(pointId => pointY[pointId]),
      customdata: ids.map(pointId => [pointId, barcodes[pointId]]),
      meta: { label: escapeHtml(category.name) },
      marker: {
        color: category.color,
        size,
        opacity
      },
      hovertemplate:
        "<b>%{meta.label}</b><br>" +
        "barcode: %{customdata[1]}<br>" +
        "x: %{x:.4f}<br>" +
        "y: %{y:.4f}<extra></extra>",
      visible: category.visible ? true : "legendonly"
    };
  });

  dataTraces.push(highlightTrace());
  return dataTraces;
}

const layout = {
  title: {
    text: escapeHtml(payload.title),
    x: 0.02,
    xanchor: "left",
    font: { size: 17 }
  },
  margin: { l: 56, r: 24, t: 54, b: 50 },
  paper_bgcolor: "#ffffff",
  plot_bgcolor: "#ffffff",
  hovermode: "closest",
  dragmode: "pan",
  legend: {
    title: { text: escapeHtml(activeKey) },
    itemsizing: "constant",
    bgcolor: "rgba(255,255,255,0.78)",
    bordercolor: "#d9dee5",
    borderwidth: 1
  },
  xaxis: {
    title: `${payload.spatial_key}[x]`,
    zeroline: false,
    showgrid: false
  },
  yaxis: {
    title: `${payload.spatial_key}[y]`,
    zeroline: false,
    showgrid: false,
    scaleanchor: "x",
    scaleratio: 1,
    autorange: payload.invert_y ? "reversed" : true
  },
  uirevision: "preserve-spatial-view"
};

const config = {
  responsive: true,
  scrollZoom: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["select2d", "lasso2d"],
  toImageButtonOptions: {
    format: "png",
    filename: "spatial_view"
  }
};

function renderPlot(initial = false) {
  const traces = buildTraces();
  if (initial) {
    return plotly.newPlot(plot, traces, layout, config);
  }
  return plotly.react(plot, traces, layout, config);
}

function refreshHighlightOnly() {
  const traceIndex = categories.length;
  const ids = selectedIds();
  return plotly.restyle(plot, {
    x: [ids.map(pointId => pointX[pointId])],
    y: [ids.map(pointId => pointY[pointId])],
    customdata: [ids.map(pointId => [pointId, barcodes[pointId]])],
    "marker.size": Math.max(Number(sizeNumber.value) + 8, 13)
  }, [traceIndex]);
}

function clearSelection(showStatus = true) {
  selectedPointId = null;
  refreshHighlightOnly();
  updateSelectionUI();
  if (showStatus) setStatus("Spot selection cleared.")
}

function registerPlotEvents() {
  if (eventsRegistered) return;
  eventsRegistered = true;

  plot.on("plotly_click", event => {
    if (!event.points || !event.points.length) return;
    const point = event.points[0];
    if (point.curveNumber >= categories.length || !point.customdata) return;
    const pointId = Number(point.customdata[0]);
    selectedPointId = pointId;
    updateSelectionUI();
    refreshHighlightOnly();
    setStatus(`Selected spatial spot ${barcodes[pointId]}.`);
  });


  plot.on("plotly_legendclick", event => {
    const categoryId = event.curveNumber;
    if (categoryId >= categories.length) return false;
    categories[categoryId].visible = !categories[categoryId].visible;
    plotly.restyle(
      plot,
      { visible: categories[categoryId].visible ? true : "legendonly" },
      [categoryId]
    );
    return false;
  });

  plot.on("plotly_legenddoubleclick", event => {
    const categoryId = event.curveNumber;
    if (categoryId >= categories.length) return false;
    categories.forEach((category, index) => {
      category.visible = index === categoryId;
    });
    plotly.restyle(
      plot,
      { visible: categories.map((_, index) => index === categoryId ? true : "legendonly") },
      categories.map((_, index) => index)
    );
    return false;
  });
}

function applyGlobalMarkerStyle() {
  if (!Number.isFinite(Number(sizeNumber.value)) || sizeNumber.value === "" ||
      !Number.isFinite(Number(opacityNumber.value)) || opacityNumber.value === "") {
    setStatus("Enter a numeric spot size and opacity.", true);
    return;
  }
  const size = Math.max(0.1, Math.min(Number(sizeNumber.max), Number(sizeNumber.value)));
  const opacity = Math.max(0, Math.min(1, Number(opacityNumber.value)));
  sizeRange.value = String(size);
  sizeNumber.value = String(size);
  opacityRange.value = String(opacity);
  opacityNumber.value = String(opacity);

  const traceIndices = categories.map((_, index) => index);
  plotly.restyle(plot, {
    "marker.size": size,
    "marker.opacity": opacity
  }, traceIndices);
  refreshHighlightOnly();
}

function updateTransformSummary() {
  const parts = [`Clockwise ${spatialTransform.rotationClockwiseDeg}°`];
  if (spatialTransform.mirrorLeftRight) parts.push("Flip horizontally");
  if (spatialTransform.mirrorUpDown) parts.push("Flip vertically");
  transformSummary.textContent =
    parts.length === 1 && spatialTransform.rotationClockwiseDeg === 0
      ? "Original orientation"
      : parts.join(" · ");
}

function transformPoint(originalX, originalY) {
  const dx = originalX - transformCenterX;
  const dy = originalY - transformCenterY;
  let rotatedX = dx;
  let rotatedY = dy;

  if (spatialTransform.rotationClockwiseDeg === 90) {
    if (payload.invert_y) {
      rotatedX = -dy;
      rotatedY = dx;
    } else {
      rotatedX = dy;
      rotatedY = -dx;
    }
  } else if (spatialTransform.rotationClockwiseDeg === 180) {
    rotatedX = -dx;
    rotatedY = -dy;
  } else if (spatialTransform.rotationClockwiseDeg === 270) {
    if (payload.invert_y) {
      rotatedX = dy;
      rotatedY = -dx;
    } else {
      rotatedX = -dy;
      rotatedY = dx;
    }
  }

  let transformedX = transformCenterX + rotatedX;
  let transformedY = transformCenterY + rotatedY;
  if (spatialTransform.mirrorLeftRight) {
    transformedX = 2 * transformCenterX - transformedX;
  }
  if (spatialTransform.mirrorUpDown) {
    transformedY = 2 * transformCenterY - transformedY;
  }
  return [transformedX, transformedY];
}

function applySpatialTransform(statusMessage) {
  for (let pointId = 0; pointId < originalPointX.length; pointId += 1) {
    const [x, y] = transformPoint(
      originalPointX[pointId],
      originalPointY[pointId]
    );
    pointX[pointId] = x;
    pointY[pointId] = y;
  }

  updateGlobalBounds();
  updateTransformSummary();
  renderPlot(false).then(() => {
    refreshHighlightOnly();
    updateSelectionUI();
    return plotly.relayout(plot, {
      "xaxis.autorange": true,
      "yaxis.autorange": payload.invert_y ? "reversed" : true
    });
  });
  setStatus(statusMessage);
}

function rotateClockwise() {
  spatialTransform.rotationClockwiseDeg =
    (spatialTransform.rotationClockwiseDeg +
      (spatialTransform.mirrorLeftRight !== spatialTransform.mirrorUpDown ? 270 : 90)) % 360;
  applySpatialTransform(
    `Rotated clockwise to ${spatialTransform.rotationClockwiseDeg}°.`
  );
}

function toggleLeftRightMirror() {
  spatialTransform.mirrorLeftRight = !spatialTransform.mirrorLeftRight;
  applySpatialTransform(
    `Horizontal flip ${spatialTransform.mirrorLeftRight ? "enabled" : "disabled"}.`
  );
}

function toggleUpDownMirror() {
  spatialTransform.mirrorUpDown = !spatialTransform.mirrorUpDown;
  applySpatialTransform(
    `Vertical flip ${spatialTransform.mirrorUpDown ? "enabled" : "disabled"}.`
  );
}

function resetSpatialTransform() {
  spatialTransform.rotationClockwiseDeg = 0;
  spatialTransform.mirrorLeftRight = false;
  spatialTransform.mirrorUpDown = false;
  applySpatialTransform("Original spatial orientation restored.");
}

function escapeCsv(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text)
    ? `"${text.replaceAll('"', '""')}"`
    : text;
}

function exportCategoryCsv(allAnnotations = false) {
  const header = [
    "barcode", "obs_key", "original_category", "edited_category", "category_changed",
    "category_color", "category_missing", "original_x", "original_y", "x", "y",
    "spatial_key", "x_col", "y_col", "rotation_clockwise_deg", "mirror_left_right",
    "mirror_up_down", "transform_center_x", "transform_center_y", "transform_invert_y",
    "spatial_transformed", "coordinate_id"
  ];
  const rows = [header.join(",")];
  const spatialChanged = spatialTransform.rotationClockwiseDeg !== 0 ||
    spatialTransform.mirrorLeftRight || spatialTransform.mirrorUpDown;
  const keys = allAnnotations ? payload.annotation_keys : [activeKey];
  for (const key of keys) {
    const state = annotationStates.get(key);
    for (let pointId = 0; pointId < barcodes.length; pointId += 1) {
      const original = state.categories[state.originalPointCategory[pointId]];
      const edited = state.categories[state.pointCategory[pointId]];
      const categoryChanged = original.missing !== edited.missing ||
        (!edited.missing && original.original_name !== edited.name);
      rows.push([
        barcodes[pointId], key, original.original_name, edited.name, categoryChanged,
        edited.color, edited.missing, originalPointX[pointId], originalPointY[pointId],
        pointX[pointId], pointY[pointId], payload.spatial_key, payload.x_col, payload.y_col,
        spatialTransform.rotationClockwiseDeg, spatialTransform.mirrorLeftRight,
        spatialTransform.mirrorUpDown, transformCenterX, transformCenterY, payload.invert_y,
        spatialChanged, payload.coordinate_id
      ].map(escapeCsv).join(","));
    }
  }
  const blob = new Blob(["\ufeff" + rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = allAnnotations ? "spatial_annotations_edits.csv" : `${activeKey}_spatial_edits.csv`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  setStatus(`Exported ${barcodes.length.toLocaleString()} displayed spots and ${keys.length} annotation(s).`);
}

function openFindModal() {
  findModal.style.display = "flex";
  barcodeInput.value = "";
  window.setTimeout(() => barcodeInput.focus(), 0);
}

function closeFindModal() {
  findModal.style.display = "none";
}

function findPointId(query) {
  if (barcodeToPointId.has(query)) return barcodeToPointId.get(query);
  const candidates = lowercaseBarcodeToIds.get(query.toLocaleLowerCase()) || [];
  return candidates.length === 1 ? candidates[0] : null;
}

function focusPoint(pointId) {
  const categoryId = pointCategory[pointId];
  categories[categoryId].visible = true;
  plotly.restyle(plot, { visible: true }, [categoryId]);

  selectedPointId = pointId;
  categorySelect.value = String(categoryId);
  syncCategoryControls();
  updateSelectionUI();
  refreshHighlightOnly();

  const span = Math.max(
    globalXMax - globalXMin,
    globalYMax - globalYMin,
    1
  );
  const half = span * 0.025;
  const x = pointX[pointId];
  const y = pointY[pointId];

  plotly.relayout(plot, {
    "xaxis.range": [x - half, x + half],
    "yaxis.range": payload.invert_y
      ? [y + half, y - half]
      : [y - half, y + half]
  });
  setStatus(`Found and highlighted ${barcodes[pointId]}.`);
}

function submitFind() {
  const query = barcodeInput.value.trim();
  if (!query) {
    setStatus("Enter a barcode.", true);
    return;
  }
  const pointId = findPointId(query);
  if (pointId === null || pointId === undefined) {
    setStatus(`Barcode not found: ${query}`, true);
    return;
  }
  closeFindModal();
  focusPoint(pointId);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
}

function updateSummary() {
  const summaryParts = [
    `${payload.n_rendered.toLocaleString()} displayed spots`,
    `${categories.length.toLocaleString()} categories`
  ];
  if (payload.omitted_nonfinite > 0) {
    summaryParts.push(
      `${payload.omitted_nonfinite.toLocaleString()} invalid-coordinate spots ignored`
    );
  }
  if (payload.sampled) {
    summaryParts.push("Sampled display; the CSV contains displayed spots only");
  }
  document.getElementById("summary").textContent = summaryParts.join(" · ");

}

function initializePage() {
  document.getElementById("pageTitle").textContent = payload.title;
  payload.annotation_keys.forEach(key => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = key;
    annotationSelect.appendChild(option);
  });
  annotationSelect.value = activeKey;
  updateSummary();
  sizeRange.max = sizeNumber.max = String(Math.max(30, payload.point_size));

  sizeRange.value = String(payload.point_size);
  sizeNumber.value = String(payload.point_size);
  opacityRange.value = String(payload.opacity);
  opacityNumber.value = String(payload.opacity);

  rebuildCategorySelectors(0);
  updateSelectionUI();
  updateTransformSummary();

  renderPlot(true).then(() => {
    registerPlotEvents();
    setStatus("Ready. Choose an annotation, then click a spot to edit its category. Export edits before closing or reloading this page.")
  });
}

annotationSelect.addEventListener("change", () => {
  activeKey = annotationSelect.value;
  ({ categories, pointCategory } = annotationStates.get(activeKey));
  layout.legend.title.text = escapeHtml(activeKey);
  rebuildCategorySelectors(0);
  updateSelectionUI();
  updateSummary();
  renderPlot(false).then(() => setStatus(`Showing annotation “${activeKey}”. Edits are kept when switching.`));
});

categorySelect.addEventListener("change", syncCategoryControls);
nameInput.addEventListener("input", updateOriginalNameHint);

document.getElementById("renameButton").addEventListener("click", () => {
  const categoryId = selectedCategoryId();
  const newName = nameInput.value.trim();
  if (!newName) {
    setStatus("Category name cannot be empty.", true);
    return;
  }
  if (categories.some((category, index) => index !== categoryId && category.name === newName)) {
    setStatus("That category name is already in use. Choose a different name.", true);
    return;
  }
  categories[categoryId].name = newName;
  plotly.restyle(plot, {
    name: escapeHtml(newName),
    meta: { label: escapeHtml(newName) }
  }, [categoryId]);
  rebuildCategorySelectors(categoryId);
  updateSelectionUI();
  setStatus(`Category display name changed to "${newName}".`);
});

document.getElementById("colorButton").addEventListener("click", () => {
  const categoryId = selectedCategoryId();
  const newColor = colorInput.value;
  categories[categoryId].color = newColor;
  plotly.restyle(plot, { "marker.color": newColor }, [categoryId]);
  setStatus(`Updated “${categories[categoryId].name}” color.`);
});

document.getElementById("onlyButton").addEventListener("click", () => {
  const categoryId = selectedCategoryId();
  categories.forEach((category, index) => {
    category.visible = index === categoryId;
  });
  plotly.restyle(
    plot,
    { visible: categories.map((_, index) => index === categoryId ? true : "legendonly") },
    categories.map((_, index) => index)
  );
  setStatus(`Showing only “${categories[categoryId].name}”.`);
});

document.getElementById("hideButton").addEventListener("click", () => {
  const categoryId = selectedCategoryId();
  categories[categoryId].visible = false;
  plotly.restyle(plot, { visible: "legendonly" }, [categoryId]);
  setStatus(`Hidden “${categories[categoryId].name}”.`);
});

document.getElementById("showAllButton").addEventListener("click", () => {
  categories.forEach(category => { category.visible = true; });
  plotly.restyle(
    plot,
    { visible: true },
    categories.map((_, index) => index)
  );
  setStatus("All categories are visible.")
});

document.getElementById("resetViewButton").addEventListener("click", () => {
  plotly.relayout(plot, {
    "xaxis.autorange": true,
    "yaxis.autorange": payload.invert_y ? "reversed" : true
  });
  setStatus("Zoom and pan have been reset.")
});

applyPointCategoryButton.addEventListener("click", () => {
  if (selectedPointId === null) {
    setStatus("Click a spatial spot first.", true);
    return;
  }

  const targetCategoryId = Number(pointCategorySelect.value);
  const pointId = selectedPointId;
  const changedCount = pointCategory[pointId] !== targetCategoryId ? 1 : 0;
  pointCategory[pointId] = targetCategoryId;

  const currentCategoryId = selectedCategoryId();
  rebuildCategorySelectors(currentCategoryId);
  renderPlot(false).then(() => {
    refreshHighlightOnly();
    updateSelectionUI();
  });
  setStatus(
    changedCount
      ? `Changed ${barcodes[pointId]} to “${categories[targetCategoryId].name}”.`
      : "The spot already belongs to the target category."
  );
});

clearSelectionButton.addEventListener("click", () => clearSelection(true));
document.getElementById("rotateClockwiseButton").addEventListener("click", rotateClockwise);
document.getElementById("mirrorLeftRightButton").addEventListener("click", toggleLeftRightMirror);
document.getElementById("mirrorUpDownButton").addEventListener("click", toggleUpDownMirror);
document.getElementById("resetTransformButton").addEventListener("click", resetSpatialTransform);

sizeRange.addEventListener("input", () => {
  sizeNumber.value = sizeRange.value;
  applyGlobalMarkerStyle();
});
sizeNumber.addEventListener("change", applyGlobalMarkerStyle);
opacityRange.addEventListener("input", () => {
  opacityNumber.value = opacityRange.value;
  applyGlobalMarkerStyle();
});
opacityNumber.addEventListener("change", applyGlobalMarkerStyle);

document.getElementById("pngButton").addEventListener("click", () => {
  plotly.downloadImage(plot, {
    format: "png",
    filename: "spatial_view",
    width: Math.max(1000, plot.clientWidth),
    height: Math.max(800, plot.clientHeight),
    scale: 2
  });
});

document.getElementById("csvButton").addEventListener("click", () => exportCategoryCsv());
document.getElementById("allCsvButton").addEventListener("click", () => exportCategoryCsv(true));
document.getElementById("findPointButton").addEventListener("click", openFindModal);
document.getElementById("submitFindButton").addEventListener("click", submitFind);
document.getElementById("closeFindButton").addEventListener("click", closeFindModal);

document.getElementById("resetPageButton").addEventListener("click", () => {
  window.location.reload();
});

barcodeInput.addEventListener("keydown", event => {
  if (event.key === "Enter") submitFind();
});

findModal.addEventListener("click", event => {
  if (event.target === findModal) closeFindModal();
});

window.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    if (findModal.style.display === "flex") {
      closeFindModal();
    } else {
      clearSelection(true);
    }
  }
});

initializePage();
