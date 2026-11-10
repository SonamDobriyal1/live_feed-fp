#!/usr/bin/env python3
"""Dummy review portal: upload a clip, see safe/unsafe frames and Grad-CAM focus.

    cd ml-model/review_portal
    python3 app.py
    open http://127.0.0.1:8090
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import cv2
from flask import Flask, jsonify, render_template, request, send_from_directory, url_for

from explain import CONF_THRESHOLD, FrameExplainer, WEIGHTS

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
UPLOADS = WORK / "uploads"
FRAMES = WORK / "frames"
SAMPLE_FPS = 2.0
MAX_FRAMES = 120
MAX_UPLOAD_MB = 80

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
explainer: FrameExplainer | None = None


def get_explainer() -> FrameExplainer:
    global explainer
    if explainer is None:
        explainer = FrameExplainer()
    return explainer


def sample_indexes(total: int, fps: float) -> list[int]:
    if total <= 0:
        return []
    step = max(1, int(round((fps or 25.0) / SAMPLE_FPS)))
    indexes = list(range(0, total, step))
    if len(indexes) > MAX_FRAMES:
        stride = len(indexes) / MAX_FRAMES
        indexes = [indexes[int(i * stride)] for i in range(MAX_FRAMES)]
    return indexes


@app.route("/")
def home():
    return render_template(
        "index.html",
        weights=str(WEIGHTS.name),
        conf=int(CONF_THRESHOLD * 100),
        sample_fps=SAMPLE_FPS,
    )


@app.route("/frames/<job_id>/<name>")
def frame_file(job_id: str, name: str):
    return send_from_directory(FRAMES / job_id, name)


@app.route("/api/analyze", methods=["POST"])
def analyze():
    video = request.files.get("video")
    if video is None or not video.filename:
        return jsonify({"ok": False, "error": "Choose a video file"}), 400
    suffix = Path(video.filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return jsonify({"ok": False, "error": "Upload an mp4 / mov / webm clip"}), 400

    UPLOADS.mkdir(parents=True, exist_ok=True)
    job_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    dest = UPLOADS / f"{job_id}{suffix}"
    video.save(dest)

    cap = cv2.VideoCapture(str(dest))
    if not cap.isOpened():
        return jsonify({"ok": False, "error": "Could not read that video"}), 400
    try:
        return _analyze_open_video(cap, dest, job_id, video.filename)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        cap.release()


def _analyze_open_video(cap, dest, job_id: str, filename: str):
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    indexes = sample_indexes(total, fps)
    out_dir = FRAMES / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    model = get_explainer()

    frames = []
    unsafe = 0
    for order, index in enumerate(indexes):
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            continue
        result = model.explain(frame)
        if result["is_unsafe"]:
            unsafe += 1
        raw_name = f"{order:03d}_raw.jpg"
        heat_name = f"{order:03d}_cam.jpg"
        cv2.imwrite(str(out_dir / raw_name), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        cv2.imwrite(str(out_dir / heat_name), result["overlay"], [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        seconds = index / fps
        frames.append(
            {
                "i": order,
                "frame_index": index,
                "time": round(seconds, 2),
                "time_label": f"{int(seconds // 60):02d}:{int(seconds % 60):02d}",
                "label": result["label"],
                "is_unsafe": result["is_unsafe"],
                "violence": round(result["violence"], 4),
                "safe": round(result["safe"], 4),
                "region": result["region"],
                "raw": url_for("frame_file", job_id=job_id, name=raw_name),
                "cam": url_for("frame_file", job_id=job_id, name=heat_name),
            }
        )
    (out_dir / "result.json").write_text(json.dumps(frames))
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "filename": filename,
            "fps": fps,
            "size": f"{width}x{height}",
            "sampled": len(frames),
            "unsafe": unsafe,
            "safe": len(frames) - unsafe,
            "threshold": CONF_THRESHOLD,
            "frames": frames,
        }
    )


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    print(f"Review portal → http://127.0.0.1:8090")
    print(f"Weights: {WEIGHTS}")
    app.run(host="127.0.0.1", port=8090, debug=False, threaded=True)


if __name__ == "__main__":
    main()
