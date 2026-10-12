#!/usr/bin/env python3
"""Gated hosted scene trial: plan by default, explicit approval before any upload or charge."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import urlopen


ENDPOINTS = {
    "golden_hour": "fal-ai/id-v2v/relight",
    "silver_screen": "fal-ai/id-v2v/relight",
    "neon_noir": "fal-ai/id-v2v",
}
PUBLISHED_RATE = 0.20  # USD/output second; an estimate, not a guaranteed price


def inspect_video(path: Path):
    output = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,avg_frame_rate,nb_frames:format=duration", "-of", "json",
         str(path)], check=True, capture_output=True, text=True, timeout=30
    )
    obj = json.loads(output.stdout)
    streams = [s for s in obj["streams"] if s.get("codec_type") == "video"]
    if len(streams) != 1:
        raise RuntimeError("Exactly one video stream is required")
    num, den = (int(v) for v in streams[0]["avg_frame_rate"].split("/"))
    if num <= 0 or den <= 0:
        raise RuntimeError("Invalid source frame rate")
    fps = num / den
    duration = float(obj["format"]["duration"])
    frames = int(streams[0].get("nb_frames") or 0) or int(duration * fps)
    if not (0 < duration <= 30 and 1 <= fps <= 120 and frames > 0):
        raise RuntimeError("Invalid source video or duration above 30 seconds")
    return fps, frames


def planning(args):
    folder = Path(args.workdir).expanduser().resolve() / args.scene
    source, reference, prompt_file = [
        folder / name for name in ("source.mp4", "stylized_first_frame.png", "prompt.txt")
    ]
    missing = [str(p) for p in (source, reference, prompt_file) if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing required media/brief: " + ", ".join(missing))
    fps, n = inspect_video(source)
    frames = min(n, args.frames)
    prompt = prompt_file.read_text().strip()
    if not prompt:
        raise RuntimeError("Empty style prompt")
    estimate = PUBLISHED_RATE * math.ceil(frames / fps)  # conservative rounding buffer
    return folder, source, reference, {
        "scene": args.scene, "model": ENDPOINTS[args.scene],
        "prompt": prompt, "frames": frames, "fps": fps, "resolution": "720p",
        "estimated_usd": round(estimate, 2),
        "billing_note": "Not a hard cost cap; check provider pricing before any paid request",
    }


def write_json(path, obj):
    temp = path.with_suffix(path.suffix + ".writing")
    temp.write_text(json.dumps(obj, indent=2))
    temp.replace(path)


def submit(args):
    folder, source, reference, info = planning(args)
    if not (args.allow_upload and args.allow_charge):
        raise RuntimeError("Required: --allow-upload --allow-charge")
    if info["estimated_usd"] > args.maximum_estimate:
        raise RuntimeError("Estimate exceeds your declared budget; nothing submitted")
    if not os.environ.get("FAL_KEY"):
        raise RuntimeError("FAL_KEY not configured; do not paste it into this repository")
    state = folder / "hosted-idv2v-trial.json"
    if state.exists():
        raise RuntimeError("Existing submission record: avoid duplicate charges; collect it instead")
    try:
        import fal_client
    except ImportError as exc:
        raise RuntimeError("Install fal-client in an isolated Python environment") from exc
    # This intentionally uploads footage to a third-party provider ONLY after both flags.
    video_url = fal_client.upload_file(str(source))
    image_url = fal_client.upload_file(str(reference))
    payload = {
        "prompt": info["prompt"], "video_url": video_url, "image_url": image_url,
        "num_frames": info["frames"], "resolution": "720p",
        "num_inference_steps": 30, "guidance_scale": 5, "vace_scale": 1,
        "enable_safety_checker": True,
    }
    if args.scene == "neon_noir":
        payload["segmentation_prompt"] = "person"
    record = {
        "status": "ATTEMPTED", "model": info["model"], "request_id": None,
        "estimated_usd": info["estimated_usd"], "created": time.time(),
        "source_url": video_url, "image_url": image_url,
    }
    # Write BEFORE calling submit so a timeout never silently causes duplicate charging.
    write_json(state, record)
    handle = fal_client.submit(info["model"], arguments=payload)
    record.update(status="QUEUED", request_id=handle.request_id)
    write_json(state, record)
    print("Submitted one request:", handle.request_id)
    print("To collect: python hosted_idv2v_trial.py collect --scene",
          args.scene, "--workdir", args.workdir)


def collect(args):
    folder, _, _, info = planning(args)
    state = folder / "hosted-idv2v-trial.json"
    if not state.exists():
        raise RuntimeError("No previous submission record")
    record = json.loads(state.read_text())
    if not record.get("request_id"):
        raise RuntimeError("Request ID unknown; consult provider dashboard rather than resubmit")
    if not os.environ.get("FAL_KEY"):
        raise RuntimeError("FAL_KEY missing")
    import fal_client
    handle = fal_client.get_handle(record["model"], record["request_id"])
    result = handle.get()  # retrieves existing request; no new paid submit
    media = result.get("video", {}).get("url")
    parsed = urlparse(media or "")
    if parsed.scheme != "https" or not parsed.hostname or not (
        parsed.hostname == "fal.media" or parsed.hostname.endswith(".fal.media")
        or parsed.hostname == "fal.run" or parsed.hostname.endswith(".fal.run")
    ):
        raise RuntimeError("Unexpected result media URL")
    target = folder / "hosted-generated-video.mp4"
    temporary = folder / "hosted-generated-video.partial"
    if target.exists() or temporary.exists():
        raise RuntimeError("Existing output/partial download will not be overwritten")
    try:
        total = 0
        with urlopen(media, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 500 * 1024 * 1024:
                    raise RuntimeError("Result exceeds 500 MB safety limit")
                output.write(chunk)
        if not total:
            raise RuntimeError("Empty downloaded media")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    record.update(status="DOWNLOADED", result_path=str(target), seed=result.get("seed"))
    write_json(state, record)
    print("Downloaded:", target)
    print("Visual quality not verified. Evaluate the entire moving clip.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "submit", "collect"))
    parser.add_argument("--workdir", default="./runs")
    parser.add_argument("--scene", choices=tuple(ENDPOINTS), required=True)
    parser.add_argument("--frames", type=int, default=81)
    parser.add_argument("--maximum-estimate", type=float, default=1.0)
    parser.add_argument("--allow-upload", action="store_true")
    parser.add_argument("--allow-charge", action="store_true")
    args = parser.parse_args()
    if not (1 <= args.frames <= 240 and .20 <= args.maximum_estimate <= 10):
        parser.error("Frames must be 1..240, estimated cost limit $0.20..$10")
    if args.action == "plan":
        _, _, _, details = planning(args)
        print(json.dumps(details, indent=2))
        print("DRY RUN: no upload, GPU use, or charge.")
    elif args.action == "submit":
        submit(args)
    else:
        collect(args)


if __name__ == "__main__":
    main()
