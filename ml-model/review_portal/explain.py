"""Classify frames and build a Grad-CAM overlay for the violence head."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import torch

from ultralytics import YOLO

INFER_SIZE = 224
CONF_THRESHOLD = 0.60
REPO = Path(__file__).resolve().parents[2]
WEIGHTS = (
    REPO / "ml-model" / "violence_yolov8n_cls-4" / "weights" / "best_final_ft.pt"
)
if not WEIGHTS.is_file():
    WEIGHTS = REPO / "pi" / "violence_yolov8n_cls-4" / "weights" / "best_final_ft.pt"


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class FrameExplainer:
    def __init__(self, weights: Path | None = None, conf: float = CONF_THRESHOLD):
        path = Path(weights) if weights else WEIGHTS
        if not path.is_file():
            raise FileNotFoundError(f"Missing weights: {path}")
        self.device = pick_device()
        self.yolo = YOLO(str(path))
        self.inner = self.yolo.model.to(self.device).eval()
        self.conf = conf
        self.names = dict(self.yolo.names)
        self.violence_idx = next(
            (i for i, n in self.names.items() if "violence" in n.lower() and "non" not in n.lower()),
            1,
        )
        self._layer = self.inner.model[8]
        self._acts = None
        self._grads = None
        self._layer.register_forward_hook(self._on_forward)
        self._layer.register_full_backward_hook(self._on_backward)

    def _on_forward(self, _module, _inputs, output):
        self._acts = output

    def _on_backward(self, _module, _grad_input, grad_output):
        self._grads = grad_output[0]

    def _tensor(self, frame_bgr: np.ndarray) -> torch.Tensor:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, (INFER_SIZE, INFER_SIZE), interpolation=cv2.INTER_AREA)
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float() / 255.0
        return tensor.to(self.device)

    def _cam(self, frame_bgr: np.ndarray, class_idx: int) -> np.ndarray:
        tensor = self._tensor(frame_bgr)
        tensor.requires_grad_(True)
        self.inner.zero_grad(set_to_none=True)
        softmax, logits = self.inner(tensor)
        score = logits[0, class_idx]
        score.backward()
        activations = self._acts[0].detach()
        gradients = self._grads[0].detach()
        weights = gradients.mean(dim=(1, 2))
        cam = torch.relu((weights[:, None, None] * activations).sum(0))
        cam = cam / (cam.max() + 1e-8)
        cam = cam.cpu().numpy().astype(np.float32)
        h, w = frame_bgr.shape[:2]
        return cv2.resize(cam, (w, h), interpolation=cv2.INTER_CUBIC)

    def _region(self, cam: np.ndarray) -> dict | None:
        height, width = cam.shape[:2]
        thresh = max(0.72, float(np.quantile(cam, 0.9)))
        mask = (cam >= thresh).astype(np.uint8)
        n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n_labels > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            best = 1 + int(np.argmax(areas))
            x, y, bw, bh, area = (int(v) for v in stats[best])
            if area >= 40 and bw * bh <= 0.5 * width * height:
                return {"x": x, "y": y, "w": bw, "h": bh}
        peak_y, peak_x = (int(v) for v in np.unravel_index(int(np.argmax(cam)), cam.shape))
        bw = max(48, width // 3)
        bh = max(48, height // 3)
        x = max(0, min(width - bw, peak_x - bw // 2))
        y = max(0, min(height - bh, peak_y - bh // 2))
        return {"x": x, "y": y, "w": bw, "h": bh}

    def explain(self, frame_bgr: np.ndarray) -> dict:
        tensor = self._tensor(frame_bgr)
        tensor.requires_grad_(True)
        self.inner.zero_grad(set_to_none=True)
        softmax, logits = self.inner(tensor)
        raw = softmax.detach()[0].float().cpu().numpy()
        scores = {self.names[i]: float(raw[i]) for i in range(len(self.names))}
        top1 = int(raw.argmax())
        violence = float(scores.get(self.names[self.violence_idx], 0.0))
        is_unsafe = top1 == self.violence_idx and violence >= self.conf
        cam_idx = self.violence_idx if is_unsafe else top1
        score = logits[0, cam_idx]
        score.backward()
        activations = self._acts[0].detach()
        gradients = self._grads[0].detach()
        weights = gradients.mean(dim=(1, 2))
        cam = torch.relu((weights[:, None, None] * activations).sum(0))
        cam = cam / (cam.max() + 1e-8)
        cam = cam.cpu().numpy().astype(np.float32)
        h, w = frame_bgr.shape[:2]
        cam = cv2.resize(cam, (w, h), interpolation=cv2.INTER_CUBIC)
        region = self._region(cam)
        overlay = self._draw(frame_bgr, cam, region, is_unsafe, violence, scores)
        return {
            "is_unsafe": is_unsafe,
            "label": "unsafe" if is_unsafe else "safe",
            "violence": violence,
            "safe": float(scores.get("non_violence", 1.0 - violence)),
            "top1": self.names[top1],
            "region": region,
            "overlay": overlay,
            "cam": cam,
        }

    def _draw(
        self,
        frame_bgr: np.ndarray,
        cam: np.ndarray,
        region: dict | None,
        is_unsafe: bool,
        violence: float,
        scores: dict[str, float],
    ) -> np.ndarray:
        heat = cv2.applyColorMap((cam * 255).astype(np.uint8), cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(frame_bgr, 0.55, heat, 0.45, 0)
        if region:
            color = (0, 0, 220) if is_unsafe else (40, 170, 80)
            x, y, bw, bh = region["x"], region["y"], region["w"], region["h"]
            cv2.rectangle(overlay, (x, y), (x + bw, y + bh), color, 2)
            cv2.putText(
                overlay,
                "model focus",
                (x, max(18, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        banner = "UNSAFE" if is_unsafe else "SAFE"
        color = (0, 0, 220) if is_unsafe else (40, 170, 80)
        cv2.rectangle(overlay, (0, 0), (overlay.shape[1], 36), color, -1)
        cv2.putText(
            overlay,
            f"{banner}  violence {violence:.0%}  safe {scores.get('non_violence', 0):.0%}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return overlay
