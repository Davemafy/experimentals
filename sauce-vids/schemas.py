"""Explicit model-facing tool contracts."""
CAPTURE = {
    "name": "sauce_capture",
    "description": "Record real public HTTPS product interactions through Chromium video, return a run ID and observed action log. No synthetic product footage.",
    "parameters": {"type": "object", "properties": {
        "url": {"type": "string", "description": "Public product URL on an approved domain"},
        "actions": {"type": "array", "description": "Observed browsing actions in order; click selectors must point to real links, no forms or credential entry", "items": {
            "type": "object", "properties": {
                "type": {"type": "string", "enum": ["wait", "scroll", "hover", "click_link"]},
                "selector": {"type": "string"},
                "pixels": {"type": "integer"},
                "seconds": {"type": "number"}
            }, "required": ["type"]}},
        "project": {"type": "string", "description": "Short lowercase project identifier"}
    }, "required": ["url", "project"]}
}
RENDER = {
    "name": "sauce_render",
    "description": "Encode genuine Sauce Vids browser recording as an MP4. Optionally use an operator-provided licensed background image. No generated visuals.",
    "parameters": {"type": "object", "properties": {
        "run_id": {"type": "string"},
        "background_asset": {"type": "string", "description": "Optional PNG or JPG filename in the configured licensed-assets folder"}
    }, "required": ["run_id"]}
}
INSPECT = {
    "name": "sauce_inspect",
    "description": "Read actual captured or rendered video metadata and recorded event receipts for Hermes to critique.",
    "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}
}
