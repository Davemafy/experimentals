"""Sauce Vids native Hermes tool registration."""
from pathlib import Path
from . import tools, schemas

def register(ctx):
    for name, handler, schema in (
        ("sauce_capture", tools.capture, schemas.CAPTURE),
        ("sauce_render", tools.render, schemas.RENDER),
        ("sauce_inspect", tools.inspect, schemas.INSPECT),
    ):
        ctx.register_tool(name=name, toolset="sauce_vids", schema=schema, handler=handler)
    ctx.register_skill("sauce-director", str(Path(__file__).parent / "skills" / "sauce-director" / "SKILL.md"))
