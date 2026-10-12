"""Compare CPU-only video appearance treatments using cached reference and masks.

No model inference, remote-service access or changes to inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np


PROFILES = {
    "balanced": {"background": 0.72, "background_reference": 0.30,
                 "foreground_reference": 0.40, "directional_key": 0.08},
    "dramatic": {"background": 0.52, "background_reference": 0.55,
                 "foreground_reference": 0.60, "directional_key": 0.16},
}


def video_capture(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot decode video: {path}")
    return cap


def linear(image: np.ndarray) -> np.ndarray:
    x = image.astype(np.float32) / 255
    return np.where(x <= 0.04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)


def srgb(image: np.ndarray) -> np.ndarray:
    x = np.clip(image, 0, 1)
    result = np.where(x <= 0.0031308, x * 12.92,
                      1.055 * np.power(x, 1 / 2.4) - .055)
    return np.rint(result * 255).astype(np.uint8)


def choose_job(root: Path) -> Path:
    renders = list(root.glob("*/render/subject-aware.mp4"))
    if not renders:
        raise RuntimeError("No completed render was found. No inputs changed.")
    return max(renders, key=lambda path: path.stat().st_mtime).parent.parent


def prepare(root: Path, output_root: Path):
    job = choose_job(root)
    paths = {
        "source": job / "source.mp4",
        "baseline": job / "render/subject-aware.mp4",
        "reference": job / "render/ic-light-reference.png",
        "masks": job / "render/moving-subject-masks.mp4",
    }
    for label, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"Missing {label}: {path}")
    destination = output_root / job.name
    outputs = [destination / f"{name}.mp4" for name in PROFILES]
    for path in outputs:
        if path.exists():
            raise RuntimeError(f"Existing experimental output will not be overwritten: {path}")
    destination.mkdir(parents=True, exist_ok=True)
    return job, paths, destination


def encode_variant(source: Path, masks: Path, output: Path, field: np.ndarray,
                   config: dict, width: int, height: int, fps: float, expected_count: int):
    cap = video_capture(source)
    matte_cap = video_capture(masks)
    temporary = output.with_name(output.stem + ".working.mp4")
    if temporary.exists():
        raise RuntimeError(f"Intermediate file exists: {temporary}")
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
        "-r", str(fps), "-i", "pipe:0", "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-threads", "2", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-shortest",
        "-movflags", "+faststart", "-n", str(temporary),
    ]
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    xx = np.arange(width, dtype=np.float32)[None, :, None]
    key = 1 + config["directional_key"] * (0.5 - xx / width)
    count = 0
    try:
        while True:
            valid, image = cap.read()
            if not valid:
                break
            has_mask, mask = matte_cap.read()
            if not has_mask:
                raise RuntimeError("Mask clip ended before source clip")
            a = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
            a = cv2.GaussianBlur(a, (0, 0), 1.25)[..., None]
            src = linear(image)
            background = src * config["background"] * np.exp(
                field * config["background_reference"])
            foreground = src * np.exp(field * config["foreground_reference"]) * key
            frame = srgb(foreground * a + background * (1 - a))
            process.stdin.write(frame.tobytes())
            count += 1
        process.stdin.close()
        stderr = process.stderr.read().decode(errors="replace")
        rc = process.wait(timeout=120)
        if rc != 0:
            raise RuntimeError(f"FFmpeg failed: {stderr[-1500:]}")
        if count != expected_count:
            raise RuntimeError(f"Frame count mismatch: {count} != {expected_count}")
        temporary.rename(output)
    finally:
        cap.release()
        matte_cap.release()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stderr.close()
        if temporary.exists():
            temporary.unlink()
    return count


def still(path: Path, index: int, thumb_width: int = 400):
    cap = video_capture(path)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Cannot read frame {index} of {path}")
        h = int(round(frame.shape[0] * thumb_width / frame.shape[1]))
        h -= h % 2
        return cv2.resize(frame, (thumb_width, h))
    finally:
        cap.release()


def make_sheet(paths: list[Path], labels: list[str], count: int, destination: Path):
    rows = []
    for index in sorted(set((0, count // 2, count - 1))):
        panels = []
        for label, path in zip(labels, paths):
            image = still(path, index)
            heading = np.zeros((32, image.shape[1], 3), dtype=np.uint8)
            cv2.putText(heading, label, (10, 23), cv2.FONT_HERSHEY_SIMPLEX,
                        .46, (250, 250, 250), 1, cv2.LINE_AA)
            panels.append(np.vstack((heading, image)))
        if len({panel.shape[0] for panel in panels}) != 1:
            raise RuntimeError("Different input aspect ratios; comparison requires aligned video")
        rows.append(np.hstack(panels))
    sheet = destination / "comparison-contact-sheet.jpg"
    if not cv2.imwrite(str(sheet), np.vstack(rows),
                       [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError("Failed to write comparison image")
    return sheet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    job, paths, destination = prepare(args.jobs_root, args.output_root)
    source = video_capture(paths["source"])
    try:
        width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(source.get(cv2.CAP_PROP_FPS))
        count = int(source.get(cv2.CAP_PROP_FRAME_COUNT))
        if not (1 <= count <= 300 and 1 <= fps <= 120 and
                width % 2 == 0 and height % 2 == 0 and
                width * height <= 1920 * 1080):
            raise RuntimeError("Unsupported source dimensions, timing or frame count")
        ok, first = source.read()
        if not ok:
            raise RuntimeError("Unable to read first source frame")
    finally:
        source.release()

    reference = cv2.imread(str(paths["reference"]), cv2.IMREAD_COLOR)
    if reference is None or reference.shape != first.shape:
        raise RuntimeError("Reference image must have the same dimensions as source")
    cap_mask = video_capture(paths["masks"])
    try:
        if (int(cap_mask.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap_mask.get(cv2.CAP_PROP_FRAME_HEIGHT))) != (width, height):
            raise RuntimeError("Mask dimensions do not match the source")
    finally:
        cap_mask.release()

    sigma = max(12, width / 35)
    original_smooth = cv2.GaussianBlur(linear(first), (0, 0), sigma)
    reference_smooth = cv2.GaussianBlur(linear(reference), (0, 0), sigma)
    field = np.clip(np.log((reference_smooth + .025) /
                           (original_smooth + .025)), -.85, .70).astype(np.float32)

    rendered = []
    for name, config in PROFILES.items():
        output = destination / f"{name}.mp4"
        n = encode_variant(paths["source"], paths["masks"], output,
                           field, config, width, height, fps, count)
        rendered.append(output)
        print(f"{name}: {n} frames, {output}", flush=True)

    sheet = make_sheet(
        [paths["source"], paths["baseline"], *rendered],
        ["SOURCE", "BASELINE", "BALANCED", "DRAMATIC"],
        count, destination,
    )
    report = {
        "input_job": job.name,
        "frame_count": count,
        "width": width,
        "height": height,
        "fps": fps,
        "profiles": PROFILES,
        "generated": [str(path) for path in rendered],
        "comparison": str(sheet),
        "quality": "Unverified: inspect full videos before claiming improvement",
    }
    (destination / "experiment.json").write_text(json.dumps(report, indent=2))
    print(f"Comparison: {sheet}", flush=True)
    print("No model inference or input changes.", flush=True)


if __name__ == "__main__":
    main()
