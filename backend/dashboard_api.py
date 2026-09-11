#!/usr/bin/env python3.8
"""
mymusic dashboard API.

Read-only aggregation layer over Navidrome (Subsonic API), the NAS filesystem
and the local process table. Stdlib only: no pip install needed on the DS218.

Runs on port 5053. Navidrome holds 4533, upload_server.py holds 5051.

Launch:
    nohup /usr/bin/python3.8 /volume1/homes/Nicolas/dashboard_api.py \
        >> /volume1/homes/Nicolas/dashboard.log 2>&1 &

Config is read from dashboard_config.json next to this file.
"""

import hashlib
import json
import os
import random
import re
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "dashboard_config.json")

DEFAULT_CONFIG = {
    "navidrome_url": "http://localhost:4533",
    "navidrome_user": "Nicolas",
    "navidrome_password": "",
    "music_path": "/volume1/music/mymusic",
    "volume_path": "/volume1",
    "navidrome_log": "/volume1/homes/Nicolas/navidrome/navidrome.log",
    "upload_server_log": "/volume1/homes/Nicolas/upload_server.log",
    "upload_server_port": 5051,
    "listen_port": 5053,
    "dashboard_token": "",
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.stderr.write(
            "dashboard_config.json missing next to dashboard_api.py. "
            "Copy dashboard_config.example.json and fill it in.\n"
        )
        sys.exit(1)
    with open(CONFIG_PATH, "r") as fh:
        user_config = json.load(fh)
    config = dict(DEFAULT_CONFIG)
    config.update(user_config)
    if not config["navidrome_password"]:
        sys.stderr.write("navidrome_password is empty in dashboard_config.json\n")
        sys.exit(1)
    if not config["dashboard_token"]:
        sys.stderr.write("dashboard_token is empty in dashboard_config.json\n")
        sys.exit(1)
    return config


CONFIG = load_config()
STARTED_AT = time.time()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, producer):
    """Return a cached value, recomputing it when older than ttl seconds.

    On failure a stale value is preferred over an error, so one flaky Subsonic
    call does not blank the whole dashboard.
    """
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
    if entry and now - entry["at"] < ttl:
        return entry["value"]
    try:
        value = producer()
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI as an error field
        if entry:
            return entry["value"]
        return {"error": "{}: {}".format(type(exc).__name__, exc)}
    with _cache_lock:
        _cache[key] = {"value": value, "at": now}
    return value


# ---------------------------------------------------------------------------
# Subsonic client
# ---------------------------------------------------------------------------


def subsonic(method, **params):
    """Call a Subsonic endpoint with salted token auth and return its payload."""
    salt = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    token = hashlib.md5(
        (CONFIG["navidrome_password"] + salt).encode("utf-8")
    ).hexdigest()

    query = {
        "u": CONFIG["navidrome_user"],
        "t": token,
        "s": salt,
        "v": "1.16.1",
        # A dedicated client name keeps this off any per-client transcoding profile.
        "c": "dashboard",
        "f": "json",
    }
    query.update({k: v for k, v in params.items() if v is not None})

    url = "{}/rest/{}?{}".format(
        CONFIG["navidrome_url"].rstrip("/"), method, urllib.parse.urlencode(query)
    )
    with urllib.request.urlopen(url, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    body = payload.get("subsonic-response", {})
    if body.get("status") != "ok":
        raise RuntimeError(body.get("error", {}).get("message", "unknown Subsonic error"))
    return body


def as_list(value):
    """Subsonic collapses single-element arrays into objects. Normalise both."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ---------------------------------------------------------------------------
# Library data
# ---------------------------------------------------------------------------


def fetch_library():
    scan = subsonic("getScanStatus")
    status = scan.get("scanStatus", {})

    artists_body = subsonic("getArtists")
    indexes = as_list(artists_body.get("artists", {}).get("index"))
    artists = []
    for index in indexes:
        artists.extend(as_list(index.get("artist")))

    return {
        "tracks": status.get("count", 0),
        "folders": status.get("folderCount", 0),
        "artists": len(artists),
        "albums": sum(a.get("albumCount", 0) or 0 for a in artists),
        "scanning": bool(status.get("scanning", False)),
        "last_scan": status.get("lastScan"),
    }


def fetch_users():
    body = subsonic("getUsers")
    users = as_list(body.get("users", {}).get("user"))
    return [
        {
            "username": u.get("username"),
            "email": u.get("email") or "",
            "admin": bool(u.get("adminRole")),
            "download": bool(u.get("downloadRole")),
            "share": bool(u.get("shareRole")),
            "playlist": bool(u.get("playlistRole")),
        }
        for u in users
    ]


def fetch_now_playing():
    body = subsonic("getNowPlaying")
    entries = as_list(body.get("nowPlaying", {}).get("entry"))
    return [
        {
            "username": e.get("username"),
            "title": e.get("title"),
            "artist": e.get("artist"),
            "album": e.get("album"),
            "player": e.get("playerName") or "",
            "minutes_ago": e.get("minutesAgo", 0),
        }
        for e in entries
    ]


def fetch_playlists():
    body = subsonic("getPlaylists")
    playlists = as_list(body.get("playlists", {}).get("playlist"))
    playlists.sort(key=lambda p: p.get("songCount", 0) or 0, reverse=True)
    return [
        {
            "name": p.get("name"),
            "owner": p.get("owner"),
            "songs": p.get("songCount", 0),
            "duration": p.get("duration", 0),
            "public": bool(p.get("public")),
            "changed": p.get("changed"),
        }
        for p in playlists
    ]


def fetch_recent_albums():
    body = subsonic("getAlbumList2", type="newest", size=12)
    albums = as_list(body.get("albumList2", {}).get("album"))
    return [
        {
            "name": a.get("name"),
            "artist": a.get("artist"),
            "songs": a.get("songCount", 0),
            "year": a.get("year"),
            "created": a.get("created"),
        }
        for a in albums
    ]


# ---------------------------------------------------------------------------
# System data
# ---------------------------------------------------------------------------


def run(cmd, timeout=10):
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    return out.decode("utf-8", "replace")


def fetch_volume():
    """Filesystem capacity in bytes. df -k is portable; df -h is not."""
    out = run(["df", "-k", CONFIG["volume_path"]], timeout=8)
    lines = [l for l in out.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        raise RuntimeError("unexpected df output")
    parts = lines[-1].split()
    total, used, free = int(parts[1]) * 1024, int(parts[2]) * 1024, int(parts[3]) * 1024
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent": round(used * 100.0 / total, 1) if total else 0,
    }


def fetch_memory():
    """/proc/meminfo rather than `free`, whose flags vary on BusyBox."""
    values = {}
    with open("/proc/meminfo", "r") as fh:
        for line in fh:
            match = re.match(r"^(\w+):\s+(\d+) kB", line)
            if match:
                values[match.group(1)] = int(match.group(2)) * 1024

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if available is None:
        available = values.get("MemFree", 0) + values.get("Cached", 0)
    used = total - available
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": available,
        "percent": round(used * 100.0 / total, 1) if total else 0,
        "swap_used_bytes": values.get("SwapTotal", 0) - values.get("SwapFree", 0),
    }


def fetch_load():
    with open("/proc/loadavg", "r") as fh:
        parts = fh.read().split()
    with open("/proc/uptime", "r") as fh:
        uptime = float(fh.read().split()[0])
    return {
        "load_1": float(parts[0]),
        "load_5": float(parts[1]),
        "load_15": float(parts[2]),
        "uptime_seconds": int(uptime),
    }


def process_info(pattern):
    """Locate a process by pattern and report its PID, start time and RSS."""
    try:
        out = run(["ps", "-eo", "pid,rss,etimes,args"], timeout=8)
    except Exception:
        out = run(["ps", "-ef"], timeout=8)

    for line in out.splitlines()[1:]:
        if pattern not in line:
            continue
        if "dashboard_api.py" in line and pattern != "dashboard_api.py":
            continue
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        try:
            pid = int(fields[0])
            rss = int(fields[1]) * 1024
            etimes = int(fields[2])
        except ValueError:
            continue
        return {"running": True, "pid": pid, "rss_bytes": rss, "uptime_seconds": etimes}
    return {"running": False, "pid": None, "rss_bytes": 0, "uptime_seconds": 0}


def fetch_services():
    navidrome = process_info("navidrome")
    upload = process_info("upload_server.py")

    try:
        url = "http://localhost:{}/".format(CONFIG["upload_server_port"])
        with urllib.request.urlopen(url, timeout=3) as resp:
            upload["http"] = resp.status < 500
    except Exception:
        # A 404 still proves the socket answers; only a connection error is fatal.
        upload["http"] = False

    try:
        subsonic("ping")
        navidrome["http"] = True
    except Exception:
        navidrome["http"] = False

    return {
        "navidrome": navidrome,
        "upload_server": upload,
        "dashboard": {
            "running": True,
            "pid": os.getpid(),
            "uptime_seconds": int(time.time() - STARTED_AT),
        },
    }


# ---------------------------------------------------------------------------
# Filesystem scan (slow: runs in the background, never inside a request)
# ---------------------------------------------------------------------------

_scan_state = {"value": None, "at": 0, "running": False}
SCAN_TTL = 6 * 3600


def scan_music_folder():
    """Walk the music tree once: total size and a breakdown by file extension.

    du over ~3,500 tracks takes a while on a DS218, so this only ever runs on a
    background thread and the request handler serves whatever it produced last.
    """
    total = 0
    by_ext = {}
    lyrics = 0
    for root, _dirs, files in os.walk(CONFIG["music_path"]):
        for name in files:
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            ext = os.path.splitext(name)[1].lower().lstrip(".") or "(none)"
            if ext == "lrc":
                lyrics += 1
            total += size
            bucket = by_ext.setdefault(ext, {"count": 0, "bytes": 0})
            bucket["count"] += 1
            bucket["bytes"] += size

    formats = [
        {"ext": ext, "count": data["count"], "bytes": data["bytes"]}
        for ext, data in by_ext.items()
    ]
    formats.sort(key=lambda f: f["bytes"], reverse=True)
    return {
        "total_bytes": total,
        "file_count": sum(f["count"] for f in formats),
        "lyrics_files": lyrics,
        "formats": formats[:12],
        "scanned_at": datetime.utcnow().isoformat() + "Z",
    }


def music_folder_async():
    now = time.time()
    if _scan_state["value"] is None or now - _scan_state["at"] > SCAN_TTL:
        if not _scan_state["running"]:
            _scan_state["running"] = True

            def worker():
                try:
                    value = scan_music_folder()
                    _scan_state["value"] = value
                    _scan_state["at"] = time.time()
                except Exception as exc:  # noqa: BLE001
                    _scan_state["value"] = {"error": str(exc)}
                    _scan_state["at"] = time.time()
                finally:
                    _scan_state["running"] = False

            threading.Thread(target=worker, daemon=True).start()

    if _scan_state["value"] is None:
        return {"pending": True}
    result = dict(_scan_state["value"])
    result["refreshing"] = _scan_state["running"]
    return result


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def tail(path, lines=40, max_bytes=200000):
    if not path or not os.path.exists(path):
        return []
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.seek(max(0, size - max_bytes))
        chunk = fh.read().decode("utf-8", "replace")
    return [l.rstrip() for l in chunk.splitlines() if l.strip()][-lines:]


def count_recent_errors(lines):
    return sum(1 for l in lines if re.search(r"\b(ERROR|FATAL|panic)\b", l))


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def build_payload():
    navidrome_log = cached("log_navidrome", 10, lambda: tail(CONFIG["navidrome_log"], 40))
    upload_log = cached("log_upload", 10, lambda: tail(CONFIG["upload_server_log"], 40))

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "services": cached("services", 15, fetch_services),
        "system": {
            "volume": cached("volume", 60, fetch_volume),
            "memory": cached("memory", 20, fetch_memory),
            "load": cached("load", 20, fetch_load),
        },
        "music_folder": music_folder_async(),
        "library": cached("library", 120, fetch_library),
        "now_playing": cached("now_playing", 15, fetch_now_playing),
        "users": cached("users", 300, fetch_users),
        "playlists": cached("playlists", 120, fetch_playlists),
        "recent_albums": cached("recent_albums", 300, fetch_recent_albums),
        "logs": {
            "navidrome": navidrome_log,
            "upload_server": upload_log,
            "navidrome_errors": count_recent_errors(navidrome_log)
            if isinstance(navidrome_log, list)
            else 0,
        },
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "mymusic-dashboard/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write(
            "[{}] {}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fmt % args)
        )

    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self):
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            supplied = header[7:].strip()
        else:
            query = urllib.parse.urlparse(self.path).query
            supplied = urllib.parse.parse_qs(query).get("token", [""])[0]
        expected = CONFIG["dashboard_token"]
        # Constant-time compare so the token cannot be guessed byte by byte.
        if len(supplied) != len(expected):
            return False
        mismatch = 0
        for a, b in zip(supplied, expected):
            mismatch |= ord(a) ^ ord(b)
        return mismatch == 0

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

        if route == "/api/health":
            self._send(200, {"status": "ok", "uptime_seconds": int(time.time() - STARTED_AT)})
            return

        if not self._authorised():
            self._send(401, {"error": "invalid or missing token"})
            return

        if route == "/api/dashboard":
            self._send(200, build_payload())
            return

        self._send(404, {"error": "unknown endpoint"})


def main():
    port = CONFIG["listen_port"]
    # Warm the slow filesystem scan at boot so the first page load has data.
    music_folder_async()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    sys.stderr.write("mymusic dashboard API listening on 0.0.0.0:{}\n".format(port))
    server.serve_forever()


if __name__ == "__main__":
    main()
