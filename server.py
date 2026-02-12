import http.server, os, glob, json, html as html_mod, urllib.parse
from datetime import datetime, timedelta

APP_NAME = os.getenv("APP_NAME", "Booking Bot")
APP_PORT = int(os.getenv("APP_PORT", "8001"))
CONFIG_PATH = "/logs/booking_config.json"
DAYS_AHEAD = 8

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"target_dates": []}

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
    except OSError:
        print(f"Warning: Cannot write to {CONFIG_PATH} (read-only filesystem)")

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        config = load_config()
        logs = sorted(glob.glob("/logs/*.log"), reverse=True)
        last_log, log_name = "", "none"
        if logs:
            log_name = os.path.basename(logs[0])
            with open(logs[0]) as f:
                last_log = html_mod.escape("".join(f.readlines()[-30:]))
        sc = len(glob.glob("/screenshots/*.png"))
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        today_plus_8 = (now + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")

        # Build scheduled dates rows
        dates_html = ""
        if config.get("target_dates"):
            for d in sorted(config["target_dates"]):
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    run_date = dt - timedelta(days=DAYS_AHEAD)
                    day_name = dt.strftime("%A")
                    run_str = run_date.strftime("%a %b %d")
                    # Check if this date's booking run has passed
                    if run_date.date() < now.date():
                        status = '<span style="color:#e94560">Past</span>'
                    elif run_date.date() == now.date():
                        status = '<span style="color:#f9a826">Today</span>'
                    else:
                        status = '<span style="color:#4CAF50">Upcoming</span>'
                    dates_html += (
                        '<div class="date-row">'
                        f'<div class="date-info">'
                        f'<strong>{d}</strong> <span class="dim">({day_name})</span><br>'
                        f'<span class="dim">Bot runs: {run_str} at 6:50 AM</span>'
                        f'</div>'
                        f'<div class="date-actions">{status} '
                        f'<form method="POST" action="/remove" style="display:inline">'
                        f'<input type="hidden" name="date" value="{d}">'
                        f'<button type="submit" class="remove-btn">Remove</button>'
                        f'</form></div></div>'
                    )
                except ValueError:
                    continue
        else:
            dates_html = '<p class="dim">No dates scheduled. Add one below.</p>'

        body = f"""<!DOCTYPE html><html><head>
<title>{APP_NAME}</title>
<meta http-equiv="refresh" content="30">
<style>
body{{font-family:Arial,sans-serif;background:#1a1a2e;color:#eee;padding:30px;max-width:800px;margin:0 auto}}
.up{{background:#4CAF50;color:#fff;padding:12px 24px;border-radius:8px;display:inline-block;font-size:20px;font-weight:bold}}
.card{{background:#16213e;border-radius:8px;padding:20px;margin:20px 0}}
pre{{background:#0f3460;padding:15px;border-radius:5px;font-size:13px;max-height:400px;overflow-y:auto;white-space:pre-wrap}}
h1{{color:#e94560;margin-bottom:20px}}
h3{{margin-top:0;color:#e94560}}
.dim{{color:#888}}
.date-row{{padding:12px 0;border-bottom:1px solid #0f3460;display:flex;justify-content:space-between;align-items:center}}
.date-row:last-of-type{{border-bottom:none}}
.date-info{{flex:1}}
.date-actions{{display:flex;align-items:center;gap:10px}}
.remove-btn{{background:#e94560;color:#fff;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-size:13px}}
.remove-btn:hover{{background:#c73851}}
.add-form{{display:flex;gap:10px;margin-top:18px;align-items:center;flex-wrap:wrap}}
.add-form input[type="date"]{{padding:10px 14px;border-radius:6px;border:1px solid #0f3460;background:#0f3460;color:#eee;font-size:15px}}
.add-btn{{background:#4CAF50;color:#fff;border:none;padding:10px 24px;border-radius:6px;cursor:pointer;font-size:15px;font-weight:bold}}
.add-btn:hover{{background:#45a049}}
.info-box{{background:#0f3460;border-radius:6px;padding:12px 16px;margin-top:12px;font-size:13px;color:#aaa}}
</style></head><body>
<h1>{html_mod.escape(APP_NAME)}</h1>
<span class="up">RUNNING</span>
<span class="dim" style="margin-left:15px">Server time: {now_str}</span>

<div class="card">
<h3>Scheduled Tee Times</h3>
{dates_html}
<form method="POST" action="/add" class="add-form">
<label style="font-size:15px">Add tee time date:</label>
<input type="date" name="date" min="{today_plus_8}" required>
<button type="submit" class="add-btn">Schedule</button>
</form>
<div class="info-box">
Pick the date you want to play. The bot automatically runs 8 days before at 6:50 AM
and books the best available time between 9:00 - 10:30 AM when the tee sheet opens at 7:00 AM.
</div>
</div>

<div class="card">
<h3>Latest Log ({html_mod.escape(log_name)})</h3>
<pre>{last_log or "No logs yet. Waiting for first scheduled run."}</pre>
</div>

<div class="card">
<h3>Screenshots</h3>
<p>{sc} saved</p>
</div>

<p class="dim">Page auto-refreshes every 30 seconds</p>
</body></html>"""

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode()
        params = urllib.parse.parse_qs(post_data)
        config = load_config()

        if self.path == "/add" and "date" in params:
            date_str = params["date"][0].strip()
            # Validate date format
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                if date_str not in config["target_dates"]:
                    config["target_dates"].append(date_str)
                    config["target_dates"].sort()
                    save_config(config)
            except ValueError:
                pass
        elif self.path == "/remove" and "date" in params:
            date_str = params["date"][0].strip()
            if date_str in config["target_dates"]:
                config["target_dates"].remove(date_str)
                save_config(config)

        # Redirect back to home
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    if not os.path.exists(CONFIG_PATH):
        save_config({"target_dates": []})
    s = http.server.HTTPServer(("0.0.0.0", APP_PORT), Handler)
    print(f"{APP_NAME} status page on port {APP_PORT}")
    s.serve_forever()
