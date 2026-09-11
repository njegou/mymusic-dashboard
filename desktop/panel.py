#!/usr/bin/env python3
"""
Fetch the mymusic dashboard payload and emit a panel-ready view of it.

    panel.py --json     compact JSON for eww (default)
    panel.py --text     Conky-flavoured text, kept for X11 sessions

Whatever happens, this prints valid output and never a traceback: the result
is rendered on the desktop, where a Python stack trace helps nobody.

Config is read from panel.env next to this script:

    MYMUSIC_URL=http://100.69.220.88:5053
    MYMUSIC_TOKEN=...
"""

import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "panel.env")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def load_env():
    settings = {"MYMUSIC_URL": "", "MYMUSIC_TOKEN": ""}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip().strip('"').strip("'")
    return settings


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------


def human_bytes(n):
    if not n:
        return "0 o"
    units = ["o", "ko", "Mo", "Go", "To"]
    i = 0
    v = float(n)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    if v >= 100 or i == 0:
        return "{:.0f} {}".format(v, units[i])
    return "{:.1f} {}".format(v, units[i])


def human_count(n):
    try:
        # Narrow no-break space: groups digits without widening the panel much.
        return "{:,}".format(int(n)).replace(",", "\u202f")
    except (TypeError, ValueError):
        return "—"


def uptime(seconds):
    if not seconds:
        return "—"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "{} j {} h".format(days, hours)
    if hours:
        return "{} h {:02d}".format(hours, minutes)
    return "{} min".format(minutes)


def level(percent):
    if percent >= 90:
        return "bad"
    if percent >= 75:
        return "warn"
    return "ok"


def truncate(value, limit):
    value = value or "—"
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def fetch(settings):
    url = settings["MYMUSIC_URL"].rstrip("/") + "/api/dashboard"
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + settings["MYMUSIC_TOKEN"]}
    )
    with urllib.request.urlopen(request, timeout=6) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# view model
# ---------------------------------------------------------------------------


def build_view(data):
    """Flatten the API payload into something a yuck template can read directly.

    All the branching lives here so the widget file stays declarative.
    """
    services = data.get("services") or {}
    system = data.get("system") or {}
    library = data.get("library") or {}
    playing = data.get("now_playing")

    view = {"ok": True, "error": "", "services": [], "meters": [],
            "library": None, "playing": []}

    for key, label in (("navidrome", "Navidrome"), ("upload_server", "Import")):
        svc = services.get(key) or {}
        if svc.get("running") and svc.get("http"):
            state, detail = "ok", uptime(svc.get("uptime_seconds"))
        elif svc.get("running"):
            state, detail = "warn", "ne répond pas"
        else:
            state, detail = "bad", "arrêté"
        view["services"].append({"label": label, "state": state, "detail": detail})

    volume = system.get("volume") or {}
    if "percent" in volume:
        view["meters"].append({
            "label": "Disque",
            "percent": volume["percent"],
            "value": "{:.0f} %".format(volume["percent"]),
            "detail": "{} libres".format(human_bytes(volume.get("free_bytes"))),
            "level": level(volume["percent"]),
        })

    memory = system.get("memory") or {}
    if "percent" in memory:
        detail = human_bytes(memory.get("used_bytes")) + " utilisés"
        if memory.get("swap_used_bytes"):
            detail += " · swap " + human_bytes(memory["swap_used_bytes"])
        view["meters"].append({
            "label": "Mémoire",
            "percent": memory["percent"],
            "value": "{:.0f} %".format(memory["percent"]),
            "detail": detail,
            "level": level(memory["percent"]),
        })

    load = system.get("load") or {}
    if "load_1" in load:
        # The DS218 is dual-core, so a load average of 2.0 saturates it.
        percent = min(100.0, (load["load_1"] / 2.0) * 100)
        view["meters"].append({
            "label": "Charge",
            "percent": percent,
            "value": "{:.2f}".format(load["load_1"]),
            "detail": "actif depuis " + uptime(load.get("uptime_seconds")),
            "level": level(percent),
        })

    if "tracks" in library:
        view["library"] = {
            "tracks": human_count(library.get("tracks")),
            "albums": human_count(library.get("albums")),
            "artists": human_count(library.get("artists")),
            "scanning": bool(library.get("scanning")),
        }

    if isinstance(playing, list):
        for entry in playing[:3]:
            view["playing"].append({
                "title": truncate(entry.get("title"), 30),
                "artist": truncate(entry.get("artist"), 22),
                "user": truncate(entry.get("username"), 10),
            })

    return view


def failed_view(message):
    return {"ok": False, "error": message, "services": [], "meters": [],
            "library": None, "playing": []}


# ---------------------------------------------------------------------------
# text rendering (Conky / plain stdout)
# ---------------------------------------------------------------------------

TEXT_COLOURS = {"ok": "${color3}", "warn": "${color4}", "bad": "${color5}"}


def render_text(view):
    if not view["ok"]:
        return "${color5}mymusic${color0}\n${color2}" + view["error"]

    out = ["${color1}mymusic${color0}"]

    for svc in view["services"]:
        out.append("{}\u25cf ${{color2}}{:<10}${{color0}}{}".format(
            TEXT_COLOURS[svc["state"]], svc["label"], svc["detail"]))

    for meter in view["meters"]:
        filled = int(round(meter["percent"] / 100.0 * 18))
        gauge = "\u2588" * filled + "\u2591" * (18 - filled)
        out.append("")
        out.append("${{color2}}{:<8}${{color0}}{}".format(meter["label"], meter["value"]))
        out.append("{}{}".format(TEXT_COLOURS[meter["level"]], gauge))
        out.append("${color2}" + meter["detail"])

    lib = view["library"]
    if lib:
        out.append("")
        out.append("${{color0}}{} morceaux".format(lib["tracks"]))
        out.append("${{color2}}{} albums · {} artistes".format(lib["albums"], lib["artists"]))

    if view["playing"]:
        out.append("")
        out.append("${color1}en écoute${color0}")
        for item in view["playing"]:
            out.append("${color0}" + item["title"])
            out.append("${{color2}}{} · {}".format(item["artist"], item["user"]))

    return "\n".join(out)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main():
    as_text = "--text" in sys.argv

    settings = load_env()
    if not settings["MYMUSIC_URL"] or not settings["MYMUSIC_TOKEN"]:
        view = failed_view("panel.env incomplet")
    else:
        try:
            view = build_view(fetch(settings))
        except urllib.error.HTTPError as exc:
            view = failed_view("jeton refusé" if exc.code == 401
                               else "HTTP {}".format(exc.code))
        except Exception:
            view = failed_view("serveur injoignable")

    if as_text:
        print(render_text(view))
    else:
        print(json.dumps(view, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
