#!/usr/bin/env python3
"""Reference-guided video restylization lab. Preparation/verification work offline.

No automatic dependency installation, downloads, deployment, or production-worker control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

SCENES = {
    "golden_hour": {
        "mode": "relight",
        "title": "Golden Hour",
        "prompt": "One uninterrupted live action take, exactly the original performers with unchanged faces, clothing, choreography, timing, camera motion and framing. The same room transformed by late afternoon sunlight from camera right: broad motivated warm shafts through existing windows, natural bounce and soft shadow falloff, rich detailed skin, fine atmospheric haze, believable contact shadows and specular reflections on the wooden floor. Photoreal cinematic exposure and detailed highlights. No cuts, no added people, no altered choreography.",
        "reference_brief": "EDIT THE EXACT SOURCE FRAME; do not compose a new scene. Keep every original face, body, costume, position, limb, window and object unchanged. Change only physically motivated golden-hour lighting; warmer key from existing windows, cooler ambient fill, realistic shadows, subtle haze and natural floor highlights. No typography, collage, overlaid logo or duplicate dancers.",
    },
    "silver_screen": {
        "mode": "relight",
        "title": "Silver Screen",
        "prompt": "The identical continuous live action performance, with precisely the source performers, face identity, expressions, clothes, motion, timing and camera. Classic 1940s black-and-white cinematography: hard motivated side key light, luminous skin tones, deep structured shadows with visible detail, graduated falloff, subtle film halation and restrained fine-grain photographic texture. Original scene geography unchanged. No additional actors, props, edits or cuts. Genuine lighting changes, not a flat grayscale conversion.",
        "reference_brief": "EDIT THE EXACT SOURCE FRAME. Preserve faces, poses, positions, costumes, foreground-background geometry and all scene objects. Create classic monochrome film lighting with a coherent hard key, soft ambient fill and controlled highlights. Avoid crushed faces, painted shading, excessive grain, posterization or typography.",
    },
    "neon_noir": {
        "mode": "restyle",
        "title": "Neon Noir",
        "prompt": "The same recognizable original performers, unchanged faces, costumes, choreography, spacing, expressions and single-camera trajectory. Reimagine the original dance venue as a believable cinematic neon-noir night interior, with motivated cyan and amber practical lighting, rich colored rim lights, shallow atmospheric haze, layered background depth and reflective surfaces. Keep the original performance and frame composition continuously. All actors remain real and consistent. No morphing, no added bodies, no extra limbs, no cuts, no text.",
        "reference_brief": "EDIT THE EXACT SOURCE FRAME, preserving the original people, count, face identities, poses, outfits and screen-space positions. Rebuild the surrounding room as a high-budget neon-noir scene with motivated cyan and warm practicals, reflective floor, believable haze, consistent camera perspective and grounded shadows. No new performers, logos, signage text or rearranged choreography. This is the scene regeneration reference, not just a recolor.",
    },
}
GIB = 1024 ** 3
MODEL_CHECKPOINT = "checkpoints/idv2v.pth"


def log(*values):
    print(*values, flush=True)


def run_checked(cmd, *, cwd=None, timeout=90):
    return subprocess.run([str(v) for v in cmd], cwd=cwd, check=True,
                          capture_output=True, text=True, timeout=timeout).stdout


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            b = stream.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def probe(path):
    result = json.loads(run_checked([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration",
        "-of", "json", path
    ]))
    vids = [s for s in result["streams"] if s.get("codec_type") == "video"]
    if len(vids) != 1:
        raise ValueError("Expected one video stream")
    s = vids[0]
    numer, denom = map(int, s["r_frame_rate"].split("/"))
    fps = numer / denom
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": fps, "frames": int(s.get("nb_frames", 0) or 0),
            "duration": float(result["format"]["duration"])}


def project(workdir, scene):
    return Path(workdir).expanduser().resolve() / scene


def prepare(args):
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    details = probe(source)
    if not (0 < details["duration"] <= 10 and details["width"] > 0
            and details["height"] > 0 and details["fps"] > 0):
        raise ValueError("Use a source clip 10 seconds or shorter with valid video.")
    root = Path(args.workdir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name, scene in SCENES.items():
        p = project(root, name)
        p.mkdir(parents=True, exist_ok=True)
        target = p / "source.mp4"
        if not target.exists():
            shutil.copy2(source, target)
        elif sha256(target) != sha256(source):
            raise RuntimeError(f"Existing source differs: {target}")
        if not (p / "prompt.txt").exists():
            (p / "prompt.txt").write_text(scene["prompt"] + "\n")
        if not (p / "reference_brief.txt").exists():
            (p / "reference_brief.txt").write_text(scene["reference_brief"] + "\n")
        if not (p / "scene.json").exists():
            with (p / "scene.json").open("w") as f:
                json.dump({"scene": name, "mode": scene["mode"],
                           "sourceSha256": sha256(target), "source": details,
                           "referenceRequired": "stylized_first_frame.png",
                           "quality": "NOT TESTED"}, f, indent=2)
        if not (p / "source_frame0.png").exists():
            run_checked(["ffmpeg", "-hide_banner", "-loglevel", "error",
                         "-i", target, "-frames:v", "1", "-y", p / "source_frame0.png"])
        log(f"PREPARED {name} ({scene['mode']}): {p}")
    log("NOT GENERATED: edited first frames are still required before video inference.")
    log("Edit each source_frame0.png according to reference_brief.txt,")
    log("and save the result beside it as stylized_first_frame.png.")


def worker_online():
    try:
        with urllib.request.urlopen("http://127.0.0.1:6006/health", timeout=2) as response:
            return bool(json.load(response).get("ok", False))
    except Exception:
        return False


def inspect(args):
    root = Path(args.workdir).expanduser().resolve()
    engine = Path(args.engine_root).expanduser().resolve()
    report = {
        "workdir": str(root), "engine": str(engine),
        "engineExists": engine.is_dir(),
        "engineVenv": (engine / ".venv/bin/python").is_file(),
        "checkpoint": (engine / MODEL_CHECKPOINT).is_file(),
        "workerOnline": worker_online(),
        "diskFreeGiB": round(shutil.disk_usage(root if root.exists() else Path("/")).free / GIB, 2),
        "hostRAMAvailableGiB": None,
        "scenes": {},
    }
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                report["hostRAMAvailableGiB"] = round(int(line.split()[1]) * 1024 / GIB, 2)
    except (FileNotFoundError, ValueError):
        pass
    for name, scene in SCENES.items():
        p = project(root, name)
        ref = p / "stylized_first_frame.png"
        cond = p / "preprocessing/orig_pixel.mp4"
        report["scenes"][name] = {
            "mode": scene["mode"],
            "source": (p / "source.mp4").is_file(),
            "reference": ref.is_file(),
            "prompt": (p / "prompt.txt").is_file(),
            "preprocessedCondition": cond.is_file() if scene["mode"] == "restyle" else "not required",
        }
    log(json.dumps(report, indent=2))
    if not report["checkpoint"]:
        log("MODEL GATE: Full official ID-V2V setup is ~96 GB, potentially exceeding available storage.")
        log("Do not download checkpoints until disk/RAM/GPU capacity and cost are approved.")
    if report["workerOnline"]:
        log("SAFETY GATE: A local worker is serving jobs on port 6006. GPU inference is blocked.")


def render(args):
    if not args.confirm_gpu:
        raise RuntimeError("GPU inference requires explicit --confirm-gpu.")
    if worker_online():
        raise RuntimeError("Existing live inference worker on port 6006: refusing to share the GPU.")
    engine = Path(args.engine_root).expanduser().resolve()
    p = project(args.workdir, args.scene)
    scene = SCENES[args.scene]
    required = [
        p / "source.mp4", p / "stylized_first_frame.png", p / "prompt.txt",
        engine / ".venv/bin/python", engine / MODEL_CHECKPOINT,
        engine / "checkpoints/wan/Wan-AI/Wan2.1-T2V-14B/models_t5_umt5-xxl-enc-bf16.pth",
        engine / "checkpoints/wan/Wan-AI/Wan2.1-T2V-14B/Wan2.1_VAE.pth",
        engine / "checkpoints/wan/Wan-AI/Wan2.1-I2V-14B-480P/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
    ]
    if scene["mode"] == "restyle":
        required.append(p / "preprocessing/orig_pixel.mp4")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing preparation/model assets (no GPU launched):\n" +
                                "\n".join(missing))
    image_details = run_checked(["ffprobe", "-v", "error", "-show_entries",
                                 "stream=width,height", "-of", "json",
                                 p / "stylized_first_frame.png"])
    streams = json.loads(image_details)["streams"]
    if not streams:
        raise ValueError("Cannot decode edited reference image")
    dims = probe(p / "source.mp4")
    ref_ratio = int(streams[0]["width"]) / int(streams[0]["height"])
    source_ratio = dims["width"] / dims["height"]
    if abs(ref_ratio / source_ratio - 1) > .08:
        raise ValueError("Edited first frame has a different aspect ratio from the source")
    output = p / "outputs" / "trial_01"
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("Trial output already exists; never overwrite generated evidence.")
    output.mkdir(parents=True, exist_ok=True)
    condition = p / "source.mp4" if scene["mode"] == "relight" else p / "preprocessing/orig_pixel.mp4"
    wan = engine / "checkpoints/wan"
    models = ("Wan-AI/Wan2.1-I2V-14B-720P:diffusion_pytorch_model*.safetensors,"
              "Wan-AI/Wan2.1-T2V-14B:models_t5_umt5-xxl-enc-bf16.pth,"
              "Wan-AI/Wan2.1-T2V-14B:Wan2.1_VAE.pth,"
              "Wan-AI/Wan2.1-I2V-14B-480P:models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth")
    cmd = [
        str(engine / ".venv/bin/python"), "-m", "idv2v.inference.pipeline",
        "--prompt", str(p / "prompt.txt"),
        "--input_image", str(p / "stylized_first_frame.png"),
        "--condition_0_path", str(condition),
        "--original_video_path", str(p / "source.mp4"),
        "--result_save_folder", str(output),
        "--output_fps", "source",
        "--model_checkpoint", str(engine / MODEL_CHECKPOINT),
        "--width", "1280", "--height", "720",
        "--num_frames_per_clip", "81", "--max_num_frames", "81",
        "--num_inference_steps", "30", "--cfg_scale", "5",
        "--vace_scale", "1", "--ref_pad_num", "-1", "--seed", "123",
        "--local_model_path", str(wan),
        "--model_id_with_origin_paths", models,
        "--vace_checkpoint_path",
        str(wan / "Wan-AI/Wan2.1-VACE-14B/diffusion_pytorch_model*.safetensors"),
    ]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    log("Starting one controlled 81-frame 720p trial:", args.scene)
    log("No model downloads will be initiated by this wrapper. A single A100 40 GB may OOM.")
    started = time.monotonic()
    with (output / "inference.log").open("w") as log_file:
        proc = subprocess.run(cmd, cwd=engine, env=env, stdout=log_file,
                              stderr=subprocess.STDOUT, timeout=args.timeout_minutes * 60)
    elapsed = round(time.monotonic() - started, 2)
    (output / "trial.json").write_text(json.dumps({
        "scene": args.scene, "returncode": proc.returncode,
        "seconds": elapsed, "originalSha256": sha256(p / "source.mp4"),
        "referenceSha256": sha256(p / "stylized_first_frame.png"),
        "quality": "NOT ASSESSED",
    }, indent=2))
    if proc.returncode:
        raise RuntimeError(f"Inference failed ({proc.returncode}); see {output/'inference.log'}")
    if not (output / "generated_video.mp4").is_file():
        raise RuntimeError("Inference returned without generated_video.mp4; quality unverified")
    log("Generated trial:", output / "generated_video.mp4")
    log("Evaluate its complete video before claiming quality.")


def evaluate(args):
    # Objective checks are smoke tests, not identity/motion realism scores.
    import cv2
    import numpy as np
    p = project(args.workdir, args.scene)
    source = p / "source.mp4"
    generated = Path(args.video).expanduser().resolve() if args.video else (
        p / "outputs/trial_01/generated_video.mp4")
    if not generated.is_file():
        raise FileNotFoundError(generated)
    original = probe(source)
    result = probe(generated)
    if result["frames"] == 0:
        raise RuntimeError("Generated video does not expose decodable frames")
    if result["width"] < 640 or result["height"] < 360:
        raise RuntimeError("Generated output too small for this quality trial")

    cap = cv2.VideoCapture(str(generated))
    seq, prev = [], None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            small = cv2.resize(frame, (160, 90)).astype(np.float32)
            lum = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean() / 255
            delta = float(np.abs(small - prev).mean()) / 255 if prev is not None else None
            seq.append({"luminance": float(lum), "frameChange": delta})
            prev = small
    finally:
        cap.release()
    if len(seq) != result["frames"]:
        raise RuntimeError(f"Bad frame decode: {len(seq)} vs {result['frames']}")
    fps_change = abs(result["fps"] - original["fps"])
    count_expected = min(original["frames"], 81) if original["frames"] else None
    flags = []
    if fps_change > .05:
        flags.append("FPS differs from source")
    if count_expected and abs(result["frames"] - count_expected) > 1:
        flags.append("Frame count differs from capped conditioning clip")
    luma = np.array([x["luminance"] for x in seq])
    differences = np.array([x["frameChange"] for x in seq[1:]])
    if np.mean(luma < .025) > .05:
        flags.append("More than 5% near-black frames")
    if np.mean(luma > .975) > .05:
        flags.append("More than 5% near-white frames")
    if len(differences) and np.mean(differences < .002) > .2:
        flags.append("More than 20% near-duplicate adjacent frames")
    report = {
        "input": original, "output": result,
        "framesDecoded": len(seq), "warningFlags": flags,
        "meanLuminance": round(float(luma.mean()), 4),
        "meanFrameChange": round(float(differences.mean()), 4) if len(differences) else None,
        "qualityPass": False,
        "qualityNote": "UNVERIFIED. Requires viewing entire video and manual ratings for identity, motion, temporal stability, cinematography, and transformation.",
    }
    manual = Path(args.ratings).expanduser() if args.ratings else None
    if manual:
        scores = json.loads(manual.read_text())
        keys = ("identity", "performance", "temporal", "cinematography", "transformation")
        if not all(isinstance(scores.get(k), int) and 0 <= scores[k] <= 20 for k in keys):
            raise ValueError(f"Manual ratings must contain 0..20 integer values: {keys}")
        total = sum(scores[k] for k in keys)
        accepted = total >= 85 and all(scores[k] >= 17 for k in keys[:3]) and not flags
        report.update({"manualScores": scores, "total": total, "qualityPass": accepted})
    dest = generated.parent / "quality-report.json"
    dest.write_text(json.dumps(report, indent=2))
    log(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "status", "render", "evaluate"))
    parser.add_argument("--source", help="Original input MP4, for prepare")
    parser.add_argument("--workdir", default="./runs")
    parser.add_argument("--scene", choices=tuple(SCENES), default="golden_hour")
    parser.add_argument("--engine-root", default="/home/video-lab/ID-V2V")
    parser.add_argument("--confirm-gpu", action="store_true")
    parser.add_argument("--timeout-minutes", type=int, default=50)
    parser.add_argument("--video", help="Generated MP4 for evaluate")
    parser.add_argument("--ratings", help="Manual ratings JSON for evaluate")
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.source:
            parser.error("prepare requires --source")
        prepare(args)
    elif args.action == "status":
        inspect(args)
    elif args.action == "render":
        if not 1 <= args.timeout_minutes <= 90:
            parser.error("--timeout-minutes must be 1..90")
        render(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
