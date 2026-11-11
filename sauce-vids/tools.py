"""Sauce Vids execution boundary. Hermes makes artistic decisions; this plugin records and renders."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import uuid
from urllib.parse import urljoin, urlsplit

ROOT = Path(os.environ.get("SAUCE_RUN_DIR", str(Path.home() / ".sauce-vids"))).expanduser()

def _receipt(**items):
    return json.dumps(items, ensure_ascii=False)

def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", value):
        raise ValueError("Invalid identifier")
    return value

def _url(value, host=None):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Invalid URL")
    p = urlsplit(value)
    hosts = {x.strip().lower() for x in os.environ.get("SAUCE_ALLOWED_HOSTS", "").split(",") if x.strip()}
    if not hosts:
        raise ValueError("Set SAUCE_ALLOWED_HOSTS to the domains you explicitly approve")
    if p.scheme != "https" or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Only approved public HTTPS origins are permitted")
    if host and p.hostname != host:
        raise ValueError("Navigation leaves the approved host")
    # The browser worker should additionally enforce egress and DNS policies.
    for answer in socket.getaddrinfo(p.hostname, 443):
        if not ipaddress.ip_address(answer[4][0]).is_global:
            raise ValueError("Host resolves to non-public IP")
    return p.hostname

def _dir(run_id):
    path = ROOT / _id(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path

def _check_actions(actions):
    if not isinstance(actions, list) or len(actions) > 24:
        raise ValueError("Maximum 24 actions")
    result = []
    for a in actions:
        if not isinstance(a, dict) or a.get("type") not in ("wait", "scroll", "hover", "click_link"):
            raise ValueError("Unsupported action")
        mode = a["type"]
        seconds = float(a.get("seconds", 0.65))
        if not 0.1 <= seconds <= 3:
            raise ValueError("Action time outside 0.1–3 seconds")
        item = {"type": mode, "seconds": seconds}
        if mode in ("hover", "click_link"):
            sel = a.get("selector", "")
            if not isinstance(sel, str) or not 1 <= len(sel) <= 150:
                raise ValueError("Missing or excessively long selector")
            item["selector"] = sel
        if mode == "scroll":
            pixels = a.get("pixels", 400)
            if type(pixels) is not int or not -1300 <= pixels <= 1300:
                raise ValueError("Scroll outside supported range")
            item["pixels"] = pixels
        result.append(item)
    return result

CURSOR = r"""(() => {
  const id='sauce-pointer';
  function mount() {
    if (document.getElementById(id)) return;
    const n=document.createElement('div');n.id=id;
    n.style.cssText='position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;display:none;width:28px;height:36px;filter:drop-shadow(0 1px 1px #0004)';
    n.innerHTML='<svg viewBox="0 0 28 36" width="28" height="36"><path d="M3 2 V27 L9 21 L15 33 L20 30 L14 19 H24 Z" fill="#17181c" stroke="white" stroke-width="2.3" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(n);
  }
  document.addEventListener('DOMContentLoaded',mount);
  document.addEventListener('mousemove',(e)=>{
    mount();const n=document.getElementById(id);
    n.style.display='block';n.style.transform='translate('+(e.clientX-4)+'px,'+(e.clientY-2)+'px)';
  },true);
})();"""

def capture(args, **kwargs):
    try:
        project = _id(args.get("project"))
        url = args.get("url", "")
        host = _url(url)
        actions = _check_actions(args.get("actions", []))
        from playwright.sync_api import sync_playwright
        run_id = project + "-" + uuid.uuid4().hex[:10]
        folder = _dir(run_id)
        events = []
        start = time.monotonic()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1440, "height": 900},
                                          record_video_dir=str(folder), record_video_size={"width": 1440, "height": 900})
            context.add_init_script(CURSOR)
            page = context.new_page()
            page.set_default_timeout(10000)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            _url(page.url, host)
            page.wait_for_timeout(900)
            events.append({"time": round(time.monotonic()-start,2), "type": "page", "url": page.url})
            for action in actions:
                mode = action["type"]
                if mode == "scroll":
                    page.mouse.wheel(0, action["pixels"])
                elif mode == "hover":
                    el = page.locator(action["selector"]).first()
                    el.scroll_into_view_if_needed()
                    box = el.bounding_box()
                    if box is None: raise RuntimeError("Target not visible")
                    page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2, steps=26)
                elif mode == "click_link":
                    el = page.locator(action["selector"]).first()
                    el.scroll_into_view_if_needed()
                    if el.evaluate("(e)=>e.tagName.toLowerCase()") != "a":
                        raise ValueError("Only actual anchor links can be clicked")
                    href = el.get_attribute("href")
                    if not href: raise ValueError("Missing href")
                    target = urljoin(page.url, href)
                    _url(target, host)
                    box = el.bounding_box()
                    if box is None: raise RuntimeError("Target not visible")
                    x,y = box["x"]+box["width"]/2, box["y"]+box["height"]/2
                    page.mouse.move(x,y,steps=25)
                    page.mouse.click(x,y)
                    page.wait_for_load_state("domcontentloaded",timeout=15000)
                    _url(page.url, host)
                page.wait_for_timeout(int(action["seconds"]*1000))
                events.append({"time": round(time.monotonic()-start,2), "type": mode,
                               "url": page.url, "selector": action.get("selector")})
            page.wait_for_timeout(700)
            video = page.video
            page.close()
            context.close()
            video.save_as(str(folder/"recording.webm"))
            browser.close()
        info = {"run_id":run_id,"source":"continuous Chromium recording","url":url,
                "events":events,"recording":str(folder/"recording.webm"),
                "claims":"Public website only; no authenticated deployment or customer action proved."}
        (folder/"capture.json").write_text(json.dumps(info,indent=2))
        return _receipt(ok=True, **info)
    except Exception as e:
        return _receipt(ok=False,error=str(e))

def render(args, **kwargs):
    try:
        folder = _dir(args.get("run_id"))
        video = folder/"recording.webm"
        if not video.is_file(): raise ValueError("Missing recorded video")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg: raise ValueError("FFmpeg is required")
        background = args.get("background_asset")
        output = folder/"final.mp4"
        command = [ffmpeg,"-y","-hide_banner","-loglevel","error","-i",str(video)]
        if background:
            if not isinstance(background,str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,90}\.(png|jpg|jpeg)",background):
                raise ValueError("Invalid background filename")
            asset_root = Path(os.environ.get("SAUCE_ASSET_DIR","")).expanduser()
            if not os.environ.get("SAUCE_ASSET_DIR"):
                raise ValueError("SAUCE_ASSET_DIR is not configured")
            asset = asset_root/background
            if not asset.is_file(): raise ValueError("Licensed background file not found")
            command += ["-loop","1","-i",str(asset),"-filter_complex",
                "[0:v]fps=30,scale=1600:900:flags=lanczos[content];"
                "[1:v]scale=1920:1080:flags=lanczos[wall];"
                "[wall][content]overlay=160:90:shortest=1,format=yuv420p[v]",
                "-map","[v]"]
        else:
            command += ["-vf","fps=30,scale=1920:1080:flags=lanczos","-an"]
        command += ["-c:v","libx264","-crf","19","-preset","veryfast",
                    "-pix_fmt","yuv420p","-movflags","+faststart",str(output)]
        result = subprocess.run(command,capture_output=True,text=True,timeout=300)
        if result.returncode: raise RuntimeError(result.stderr[-1500:])
        receipt={"run_id":args["run_id"],"video":str(output),"bytes":output.stat().st_size,
                 "background_asset":background or None,"audio":"none","source":"real browser recording"}
        (folder/"render.json").write_text(json.dumps(receipt,indent=2))
        return _receipt(ok=True,**receipt)
    except Exception as e:
        return _receipt(ok=False,error=str(e))

def inspect(args, **kwargs):
    try:
        folder = _dir(args.get("run_id"))
        path = folder/"final.mp4"
        if not path.is_file(): raise ValueError("Render first")
        ffprobe=shutil.which("ffprobe")
        if not ffprobe: raise ValueError("ffprobe is required")
        res = subprocess.run([ffprobe,"-v","error","-show_streams","-show_format",
                              "-of","json",str(path)],capture_output=True,text=True,timeout=20,check=True)
        data = json.loads(res.stdout)
        capture_file = folder/"capture.json"
        provenance=json.loads(capture_file.read_text()) if capture_file.is_file() else {}
        return _receipt(ok=True,run_id=args["run_id"],video=str(path),
                        video_metadata=data,events=provenance.get("events",[]),
                        claims=provenance.get("claims"))
    except Exception as e:
        return _receipt(ok=False,error=str(e))
