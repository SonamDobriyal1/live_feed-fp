const form = document.getElementById("upload-form");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const strip = document.getElementById("strip");
const timeline = document.getElementById("timeline");
const hero = document.getElementById("hero");
const caption = document.getElementById("caption");
const detail = document.getElementById("detail");
const submit = form.querySelector("button");

let frames = [];
let filter = "all";
let current = 0;
let view = "cam";

function pct(value) {
  return `${Math.round(value * 100)}%`;
}

function visibleFrames() {
  if (filter === "unsafe") return frames.filter((frame) => frame.is_unsafe);
  if (filter === "safe") return frames.filter((frame) => !frame.is_unsafe);
  return frames;
}

function show(index) {
  const frame = frames[index];
  if (!frame) return;
  current = index;
  hero.src = view === "raw" ? frame.raw : frame.cam;
  caption.textContent = `${frame.time_label} · ${frame.label} · violence ${pct(frame.violence)}`;
  const region = frame.region
    ? `${frame.region.w}×${frame.region.h} at ${frame.region.x},${frame.region.y}`
    : "whole frame (no tight hotspot)";
  detail.innerHTML = `
    <dl>
      <div><dt>Decision</dt><dd>${frame.label}</dd></div>
      <div><dt>Time</dt><dd>${frame.time_label}</dd></div>
      <div>
        <dt>Violence</dt>
        <dd>${pct(frame.violence)}<div class="bar"><span style="width:${pct(frame.violence)}"></span></div></dd>
      </div>
      <div>
        <dt>Safe</dt>
        <dd>${pct(frame.safe)}<div class="bar ok"><span style="width:${pct(frame.safe)}"></span></div></dd>
      </div>
      <div><dt>Focus box</dt><dd>${region}</dd></div>
      <div><dt>Sampled frame</dt><dd>#${frame.frame_index}</dd></div>
    </dl>
    <p style="margin:14px 0 0;color:#6d7f93;font-size:.88rem">
      The coloured overlay is Grad-CAM: hotter pixels are the region that most increased the
      ${frame.is_unsafe ? "unsafe" : "safe"} score. The box is the strongest blob of that heatmap.
    </p>
  `;
  for (const node of document.querySelectorAll("[data-frame]")) {
    node.classList.toggle("is-on", Number(node.dataset.frame) === index);
  }
}

function render() {
  const shown = visibleFrames();
  timeline.innerHTML = frames.map((frame, index) => (
    `<button type="button" class="${frame.is_unsafe ? "unsafe" : "safe"}" data-frame="${index}" title="${frame.time_label} ${frame.label}"></button>`
  )).join("");
  strip.innerHTML = shown.map((frame) => (
    `<button type="button" class="${frame.is_unsafe ? "unsafe" : "safe"}" data-frame="${frame.i}">
      <img src="${frame.cam}" alt="${frame.label} at ${frame.time_label}">
      <span>${frame.time_label} ${frame.label}</span>
    </button>`
  )).join("");
  const pick = shown[0] ? shown[0].i : 0;
  show(pick);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.getElementById("video").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("video", file);
  submit.disabled = true;
  statusEl.hidden = false;
  statusEl.textContent = "Scoring frames and building heatmaps…";
  resultEl.hidden = true;
  try {
    const response = await fetch("/api/analyze", { method: "POST", body });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "Analyze failed");
    frames = data.frames;
    document.getElementById("kpi-sampled").textContent = data.sampled;
    document.getElementById("kpi-unsafe").textContent = data.unsafe;
    document.getElementById("kpi-safe").textContent = data.safe;
    document.getElementById("kpi-file").textContent = data.filename;
    statusEl.textContent = `${data.filename} · ${data.size} · ${data.sampled} frames`;
    resultEl.hidden = false;
    filter = "all";
    for (const chip of document.querySelectorAll(".chip")) {
      chip.classList.toggle("is-on", chip.dataset.filter === "all");
    }
    render();
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

document.body.addEventListener("click", (event) => {
  const viewChip = event.target.closest("[data-view]");
  if (viewChip) {
    view = viewChip.dataset.view;
    for (const node of document.querySelectorAll("[data-view]")) {
      node.classList.toggle("is-on", node === viewChip);
    }
    show(current);
    return;
  }
  const chip = event.target.closest("[data-filter]");
  if (chip) {
    filter = chip.dataset.filter;
    for (const node of document.querySelectorAll("[data-filter]")) {
      node.classList.toggle("is-on", node === chip);
    }
    render();
    return;
  }
  const tick = event.target.closest("[data-frame]");
  if (tick) show(Number(tick.dataset.frame));
});
