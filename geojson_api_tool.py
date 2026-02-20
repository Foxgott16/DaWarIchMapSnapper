#!/usr/bin/env python3
"""
GeoJSON API Tool: Reads a GeoJSON file, converts it per api-doku.txt
(Geoapify Map Matching) to waypoints, sends them via POST to the API,
and saves the response as .geojson. Config contains only api_url and api_key.
"""

import json
import queue
import sys
import threading
import time
from configparser import ConfigParser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import (
    Button,
    END,
    E,
    Frame,
    Label,
    N,
    S,
    Scrollbar,
    Text,
    W,
    filedialog,
    messagebox,
)
from tkinter import Tk

import requests


# --- Configuration (only api_url and api_key in config.ini) ---

CONFIG_NAME = "config.ini"
# Per api-doku.txt: POST, Content-Type application/json, API key as query parameter
MAPMATCH_MODE = "drive"
# API limit: max 1000 waypoints per request
MAX_WAYPOINTS_PER_REQUEST = 1000
# Free plan: 3000 credits/day, max 5 requests/second → delay between batches at least 0.2 s
FREE_PLAN_MAX_REQUESTS_PER_SECOND = 5
DELAY_BETWEEN_BATCHES_SEC = 1.0 / FREE_PLAN_MAX_REQUESTS_PER_SECOND  # 0.2 s, stays under 5/s
REQUEST_TIMEOUT = 180
API_RETRIES = 3
RETRY_DELAY_SEC = 3


def load_config() -> ConfigParser:
    """Loads config.ini."""
    config = ConfigParser()
    base = Path(__file__).resolve().parent
    config_path = base / CONFIG_NAME
    if not config_path.exists():
        raise FileNotFoundError(f"{CONFIG_NAME} not found. Please create it.")
    config.read(config_path, encoding="utf-8")
    return config


def get_api_url_and_key(config: ConfigParser) -> tuple[str, str]:
    """Reads only API URL and API key from config.ini (only plain-text values)."""
    if not config.has_section("api"):
        raise ValueError("Config must have an [api] section with api_url and api_key.")
    api_url = (config.get("api", "api_url", fallback="") or "").strip().rstrip("/")
    api_key = (config.get("api", "api_key", fallback="") or "").strip()
    if not api_url or not api_key:
        raise ValueError("api_url and api_key must be set in config.ini.")
    return api_url, api_key


def build_request_url(api_url: str, api_key: str) -> str:
    """Builds the request URL with apiKey as query parameter (per api-doku.txt)."""
    sep = "&" if "?" in api_url else "?"
    return f"{api_url}{sep}apiKey={api_key}"


# --- GeoJSON → Waypoints (per api-doku.txt) ---

def _timestamp_to_iso(ts) -> str:
    """Converts Unix timestamp or similar to ISO8601 (as in api-doku)."""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(ts, str):
        return ts
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def geojson_to_mapmatch_body(geojson: dict) -> dict:
    """
    Converts a GeoJSON FeatureCollection (points) to the body for the
    Geoapify Map-Matching API: {"mode": "drive", "waypoints": [...]}.
    Each waypoint: {"timestamp": "ISO8601", "location": [lon, lat]}.
    """
    features = geojson.get("features") or []
    waypoints = []
    for i, f in enumerate(features):
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        props = f.get("properties") or {}
        ts = props.get("timestamp") or props.get("t") or (i * 10)
        waypoints.append({
            "timestamp": _timestamp_to_iso(ts),
            "location": [lon, lat],
        })
    return {"mode": MAPMATCH_MODE, "waypoints": waypoints}


# --- API call (per api-doku.txt: POST, application/json) ---

def _response_to_features(resp: dict) -> list:
    """Extracts features from a Geoapify response (FeatureCollection or single Feature)."""
    if isinstance(resp.get("features"), list):
        return list(resp["features"])
    if resp.get("type") == "Feature":
        return [resp]
    if "geometry" in resp:
        return [{"type": "Feature", "geometry": resp["geometry"], "properties": resp.get("properties", {})}]
    return []


def send_to_api(body: dict, url: str, log_callback=None) -> dict:
    """POST with Content-Type: application/json (per api-doku.txt). Retries on connection failure."""
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)

    headers = {"Content-Type": "application/json"}
    last_err = None
    for attempt in range(1, API_RETRIES + 1):
        try:
            log(f"Request: POST {url.split('?')[0]}... (attempt {attempt}/{API_RETRIES})")
            resp = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
            log(f"Response status: {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            log(f"HTTP error: {e}", "error")
            if e.response is not None and e.response.text:
                log(e.response.text[:500], "error")
            raise
        except (requests.exceptions.ConnectionError, OSError) as e:
            last_err = e
            log(f"Connection error (attempt {attempt}/{API_RETRIES}): {e}", "error")
            if attempt < API_RETRIES:
                log(f"Waiting {RETRY_DELAY_SEC}s before retry...", "info")
                time.sleep(RETRY_DELAY_SEC)
            else:
                raise requests.exceptions.RequestException(str(last_err)) from last_err
        except requests.exceptions.RequestException as e:
            log(f"Request error: {e}", "error")
            raise
        except json.JSONDecodeError as e:
            log(f"Response is not valid JSON: {e}", "error")
            raise


def save_geojson(data: dict, out_path: str) -> None:
    """Saves the API response as .geojson (JSON)."""
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- Read GeoJSON ---

def read_geojson(path: str) -> dict:
    """Reads and parses a GeoJSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --- GUI ---

class LogView:
    def __init__(self, parent, **kwargs):
        self.frame = Frame(parent, **kwargs)
        self.text = Text(
            self.frame,
            wrap="word",
            height=12,
            state="normal",
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
        )
        scroll = Scrollbar(self.frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky=(N, S, E, W))
        scroll.grid(row=0, column=1, sticky=(N, S))
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        self.text.tag_configure("info", foreground="#9cdcfe")
        self.text.tag_configure("error", foreground="#f48771")
        self.text.tag_configure("success", foreground="#4ec9b0")

    def log(self, msg: str, level: str = "info"):
        self.text.insert(END, msg + "\n", level)
        self.text.see(END)
        self.text.update_idletasks()

    def clear(self):
        self.text.delete("1.0", END)


def run_pipeline(
    input_path: str,
    api_url: str,
    api_key: str,
    output_dir: str,
    log_callback,
) -> str | None:
    """Reads GeoJSON, converts to waypoints, sends to API, saves response. log_callback(msg, level)."""
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)

    log(f"Input: {input_path}")
    try:
        geojson = read_geojson(input_path)
        features = geojson.get("features") or []
        log(f"GeoJSON read: type={geojson.get('type', '?')}, features={len(features)}")

        body = geojson_to_mapmatch_body(geojson)
        waypoints = body["waypoints"]
        log(f"Waypoints for map matching: {len(waypoints)} (mode={MAPMATCH_MODE})")
        if not waypoints:
            log("No valid points (coordinates) found.", "error")
            return None

        url = build_request_url(api_url, api_key)

        # API allows max 1000 waypoints per request → split into chunks
        all_features = []
        total_batches = (len(waypoints) + MAX_WAYPOINTS_PER_REQUEST - 1) // MAX_WAYPOINTS_PER_REQUEST
        for i in range(0, len(waypoints), MAX_WAYPOINTS_PER_REQUEST):
            if i > 0:
                time.sleep(DELAY_BETWEEN_BATCHES_SEC)
            chunk = waypoints[i : i + MAX_WAYPOINTS_PER_REQUEST]
            chunk_body = {"mode": MAPMATCH_MODE, "waypoints": chunk}
            batch_num = (i // MAX_WAYPOINTS_PER_REQUEST) + 1
            log(f"Batch {batch_num}/{total_batches} ({len(chunk)} Waypoints)...")
            response = send_to_api(chunk_body, url, log_callback=log_callback)
            all_features.extend(_response_to_features(response))

        log(f"API responses merged: {len(all_features)} features.", "success")
        log(f"This run: {total_batches} API request(s) (Free plan: 3000 credits/day).", "info")

        base = Path(input_path).stem
        out_dir = Path(output_dir) if output_dir else Path(input_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{base}_response.geojson"
        merged = {"type": "FeatureCollection", "features": all_features}
        save_geojson(merged, str(out_path))
        log(f"Saved: {out_path}", "success")
        return str(out_path)
    except FileNotFoundError as e:
        log(f"File not found: {e}", "error")
        return None
    except json.JSONDecodeError as e:
        log(f"Invalid GeoJSON: {e}", "error")
        return None
    except ValueError as e:
        log(str(e), "error")
        return None
    except requests.exceptions.RequestException as e:
        log(f"API error: {e}", "error")
        return None
    except Exception as e:
        log(f"Error: {type(e).__name__}: {e}", "error")
        return None


def main():
    root = Tk()
    root.title("GeoJSON API Tool (Geoapify Map Matching)")
    root.minsize(500, 400)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    try:
        config = load_config()
        api_url, api_key = get_api_url_and_key(config)
        output_dir = (config.get("output", "output_dir", fallback="") or "").strip() if config.has_section("output") else ""
    except Exception as e:
        messagebox.showerror("Configuration", str(e))
        sys.exit(1)

    log_view = LogView(root)
    log_view.frame.grid(row=1, column=0, sticky=(N, S, E, W), padx=5, pady=5)

    log_queue = queue.Queue()
    current_file = [None]

    def choose_file():
        path = filedialog.askopenfilename(
            title="Select GeoJSON file",
            filetypes=[("GeoJSON", "*.geojson *.json"), ("All", "*.*")],
        )
        if path:
            current_file[0] = path
            path_label.config(text=Path(path).name)
            log_view.log(f"Selected: {path}")

    def thread_safe_log(msg, level="info"):
        log_queue.put((msg, level))

    def process_log_queue():
        try:
            while True:
                msg, level = log_queue.get_nowait()
                if msg == "__done__":
                    send_btn.config(state="normal")
                    return
                log_view.log(msg, level or "info")
        except queue.Empty:
            pass
        root.after(150, process_log_queue)

    def run():
        if not current_file[0]:
            messagebox.showwarning("File", "Please select a GeoJSON file first.")
            return
        log_view.clear()
        send_btn.config(state="disabled")

        def worker():
            try:
                run_pipeline(
                    current_file[0],
                    api_url,
                    api_key,
                    output_dir,
                    log_callback=thread_safe_log,
                )
            finally:
                log_queue.put(("__done__", None))

        threading.Thread(target=worker, daemon=True).start()
        process_log_queue()

    top = Frame(root)
    top.grid(row=0, column=0, sticky=(E, W), padx=5, pady=5)
    top.columnconfigure(1, weight=1)
    Button(top, text="Choose file…", command=choose_file).grid(row=0, column=0, padx=(0, 8))
    path_label = Label(top, text="No file selected", anchor=W)
    path_label.grid(row=0, column=1, sticky=(E, W))
    send_btn = Button(top, text="Send to API & save", command=run)
    send_btn.grid(row=0, column=2, padx=(8, 0))

    log_view.log("Ready (Geoapify Map Matching). Choose a file and send.")
    log_view.log("Free plan: max 5 requests/s, 3000 credits/day – batches are throttled accordingly.", "info")

    root.mainloop()


if __name__ == "__main__":
    main()
