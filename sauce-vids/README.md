# Sauce Vids — Hermes plugin

Hermes directs a product film. Sauce Vids records *continuous real Chromium video* and renders it with operator-provided licensed visual assets using FFmpeg.

## Install

Requirements: Python 3.11+, FFmpeg (including ffprobe), Playwright Chromium.

```bash
pip install playwright
python -m playwright install chromium
# Install ffmpeg through the OS package manager
export SAUCE_ALLOWED_HOSTS=www.brimble.io,brimble.io
hermes plugins install ./sauce-vids --no-enable
hermes plugins enable sauce-vids
hermes plugins doctor ./sauce-vids
```

The plugin registers `sauce_capture`, `sauce_render` and `sauce_inspect` plus the `sauce-director` skill. It does not embed an LLM or claim that Hermes has already directed the example film.

## Recording a truthful test

Ask Hermes to inspect the public Brimble site and record an approved link navigation. Captures are saved under `~/.sauce-vids/<run_id>/recording.webm` with an actual action receipt. Render with `sauce_render({run_id})`. To add a professionally designed background, save an appropriately licensed PNG/JPG in a directory and set `SAUCE_ASSET_DIR`; pass its filename as `background_asset`.

The renderer intentionally contains **no built-in gradient template or fake UI**. Audio is not synthesized; a licensed soundtrack or ElevenLabs track should be added through an approved post-production workflow.

## Demo and provenance

A separate manually directed Brimble film was produced during development. It proves the capture/editing concept, **not** autonomous Hermes directing. The live public Brimble agent page includes illustrative marketing components; these are not an authenticated application deployment.

This is an MVP. It has not been installed and tested against a live Hermes gateway or reviewed for production-grade arbitrary-URL hosting. Restrict workers to operator-approved domains and enforce external network/DNS policy. Permission is required for non-public pages and state changes.

## Credits

The earlier reference composition was adapted from the MIT-licensed [Third Space Interactive screen-demo](https://github.com/Third-Space-interactive/screen-demo). This standalone Python capture/render plugin does not vendor that source code. Brimble brand assets and third-party audio are **not redistributed** in this repository.
