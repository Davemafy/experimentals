# Video Appearance Lab

A small, standalone laboratory for comparing appearance-transfer and relighting compositions on **existing footage**.

The first experiment reuses a completed reference-frame image and a saved moving-subject mask video. It produces two graded variants and a four-way comparison contact sheet. It does **not** download models, start GPU inference, manage a remote service, or alter the input files.

## Inputs

Point `--jobs-root` to a directory of completed video-processing jobs. Each job must contain:

```text
<jobs-root>/<job-id>/
  source.mp4
  render/
    subject-aware.mp4
    ic-light-reference.png
    moving-subject-masks.mp4
```

The most recently completed job is chosen automatically.

## Dependencies

Python 3.10+, NumPy, OpenCV (`cv2`), and FFmpeg with `ffprobe` available on `PATH`.

## Usage

```bash
python video_appearance_lab.py \
  --jobs-root /path/to/completed-jobs \
  --output-root /path/to/experiment-output
```

Outputs go to `<output-root>/<job-id>/`:

- `balanced.mp4` — moderate source-detail-preserving lighting adjustment
- `dramatic.mp4` — stronger contrast and reference-derived color variation
- `comparison-contact-sheet.jpg` — start, midpoint, and end comparisons
- `experiment.json` — parameters and artifact paths

Source footage, reference image, mask video and baseline render are read-only. Existing experiment MP4s are never overwritten.

## Method and limitations

The script computes a low-frequency, per-channel log exposure difference between the original first frame and its edited reference. It applies bounded gain to source pixels with distinct foreground/background weights using previously generated masks.

This is **experimental appearance transfer**, not physically accurate relighting, temporal diffusion, or a matting improvement. The spatial gain remains anchored to the initial image and may not track moving subjects or camera motion correctly. Encoding success does not demonstrate better quality.

Review the entire exported video, not only the contact sheet. Pay attention to temporal flicker, matte boundaries, subject fidelity, background brightness and whether the look is actually more convincing.

No source media, credentials, rendered artifacts or service configuration belong in this repository.

## License

No license is granted unless a LICENSE file is added.
