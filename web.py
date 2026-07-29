"""FastAPI dashboard: status, logs, live browser view with click/type
passthrough ("Take Control"), and worker controls.

Protected by HTTP Basic auth — set DASHBOARD_PASSWORD as a Replit Secret.
Fails closed: with no password configured, everything returns 503.
"""

import os
import secrets as pysecrets

from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from browser import VIEWPORT
from status import Status

security = HTTPBasic()


def create_app(executor, status: Status):
    app = FastAPI(title="Golf Bot")

    def auth(credentials: HTTPBasicCredentials = Depends(security)):
        expected = os.getenv('DASHBOARD_PASSWORD')
        if not expected:
            raise HTTPException(503, "Set the DASHBOARD_PASSWORD secret first.")
        if not pysecrets.compare_digest(credentials.password, expected):
            raise HTTPException(401, "Bad password",
                                headers={"WWW-Authenticate": "Basic"})
        return True

    @app.get("/api/status")
    def api_status(_=Depends(auth)):
        return status.snapshot()

    @app.get("/api/screenshot.png")
    def api_screenshot(_=Depends(auth)):
        try:
            png = executor.submit(lambda m: m.screenshot_bytes(), timeout=20)
            return Response(png, media_type="image/png",
                            headers={"Cache-Control": "no-store"})
        except Exception as e:
            raise HTTPException(409, f"Browser busy or unavailable: {e}")

    @app.post("/api/click")
    def api_click(data: dict = Body(...), _=Depends(auth)):
        x = float(data['x']) * VIEWPORT['width']
        y = float(data['y']) * VIEWPORT['height']
        executor.submit(lambda m: m.click_at(x, y), timeout=20)
        status.event(f"Manual click at ({x:.0f},{y:.0f})")
        return {"ok": True}

    @app.post("/api/type")
    def api_type(data: dict = Body(...), _=Depends(auth)):
        text = str(data.get('text', ''))[:500]
        executor.submit(lambda m: m.type_text(text), timeout=30)
        status.event("Manual keyboard input")
        return {"ok": True}

    @app.post("/api/key")
    def api_key(data: dict = Body(...), _=Depends(auth)):
        key = str(data.get('key', 'Enter'))
        if key not in ('Enter', 'Tab', 'Escape', 'Backspace'):
            raise HTTPException(400, "Unsupported key")
        executor.submit(lambda m: m.press_key(key), timeout=20)
        return {"ok": True}

    @app.post("/api/pause")
    def api_pause(_=Depends(auth)):
        status.pause("Paused manually from dashboard")
        return {"ok": True}

    @app.post("/api/resume")
    def api_resume(_=Depends(auth)):
        status.resume()
        return {"ok": True}

    @app.post("/api/restart-browser")
    def api_restart(_=Depends(auth)):
        executor.submit(lambda m: m.restart(), timeout=180)
        status.event("Browser restarted from dashboard")
        status.set(browser_ok=True)
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(_=Depends(auth)):
        return DASHBOARD_HTML

    return app


DASHBOARD_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Golf Bot</title>
<style>
  body{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
  header{padding:12px 16px;background:#1e293b;font-weight:700}
  .wrap{padding:12px 16px;max-width:900px;margin:0 auto}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
  .card{background:#1e293b;border-radius:10px;padding:10px}
  .card b{display:block;font-size:11px;text-transform:uppercase;color:#94a3b8;margin-bottom:4px}
  .ok{color:#4ade80}.bad{color:#f87171}.warn{color:#fbbf24}
  button{background:#334155;color:#e2e8f0;border:0;border-radius:8px;padding:10px 14px;margin:4px 4px 4px 0;font-size:14px}
  button.primary{background:#2563eb}
  #shot{width:100%;border-radius:10px;border:1px solid #334155;cursor:crosshair;display:none}
  input[type=text]{background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:10px;width:60%}
  #log{background:#020617;border-radius:10px;padding:10px;font-family:ui-monospace,monospace;font-size:11px;
       white-space:pre-wrap;max-height:300px;overflow-y:auto;margin-top:12px}
  h3{margin:16px 0 8px}
</style></head><body>
<header>⛳ Golf Bot</header>
<div class="wrap">
  <div class="cards">
    <div class="card"><b>Browser</b><span id="browser">…</span></div>
    <div class="card"><b>Login</b><span id="login">…</span></div>
    <div class="card"><b>Worker</b><span id="paused">…</span></div>
    <div class="card"><b>Last result</b><span id="last">…</span></div>
  </div>
  <div class="card" style="margin-top:8px"><b>Next action</b><span id="next">…</span></div>

  <h3>Controls</h3>
  <button onclick="post('/api/pause')">Pause</button>
  <button class="primary" onclick="post('/api/resume')">Resume</button>
  <button onclick="post('/api/restart-browser')">Restart Browser</button>
  <button class="primary" onclick="toggleControl()" id="ctlbtn">Take Control</button>

  <div id="control" style="display:none">
    <h3>Live browser — tap the page to click</h3>
    <img id="shot">
    <div style="margin-top:8px">
      <input type="text" id="txt" placeholder="Type text…">
      <button onclick="sendText()">Send</button>
      <button onclick="post('/api/key',{key:'Enter'})">Enter</button>
    </div>
  </div>

  <h3>Event log</h3>
  <div id="log">loading…</div>
</div>
<script>
let controlling=false, shotTimer=null;
async function post(url,body){await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body||{})}); refresh();}
async function refresh(){
  const r=await fetch('/api/status'); if(!r.ok) return; const s=await r.json();
  set('browser', s.browser_ok?'<span class=ok>running</span>':'<span class=bad>down</span>');
  set('login', s.login_ok===null?'<span class=warn>unknown</span>':
      s.login_ok?'<span class=ok>logged in</span>':'<span class=bad>logged out</span>');
  set('paused', s.paused?'<span class=warn>PAUSED: '+(s.pause_reason||'')+'</span>':'<span class=ok>active</span>');
  set('last', s.last_result||'—'); set('next', s.next_action||'—');
  document.getElementById('log').textContent=s.events.join('\\n');
}
function set(id,html){document.getElementById(id).innerHTML=html;}
function toggleControl(){
  controlling=!controlling;
  document.getElementById('control').style.display=controlling?'block':'none';
  document.getElementById('shot').style.display=controlling?'block':'none';
  document.getElementById('ctlbtn').textContent=controlling?'Stop Controlling':'Take Control';
  if(controlling){grabShot(); shotTimer=setInterval(grabShot,2500);}
  else clearInterval(shotTimer);
}
async function grabShot(){
  const img=document.getElementById('shot');
  img.src='/api/screenshot.png?t='+Date.now();
}
document.getElementById('shot').addEventListener('click',e=>{
  const r=e.target.getBoundingClientRect();
  post('/api/click',{x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height});
  setTimeout(grabShot,800);
});
function sendText(){const t=document.getElementById('txt');post('/api/type',{text:t.value});t.value='';}
refresh(); setInterval(refresh,5000);
</script></body></html>
"""
