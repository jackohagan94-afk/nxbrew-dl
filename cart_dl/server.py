import os, sys, json, time, webbrowser, threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from .util.io_tools import load_yml, save_yml
from .util.html_tools import get_game_dict
from .util.igdb_tools import IGDBClient, filter_game_dict, DEFAULT_MIN_RATING
from .scraper.scraper import CartDL

app = FastAPI(title="cart-dl", version="0.8.0")

# Prefer config from exe directory, fall back to cwd
_exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.getcwd()
CONFIG_FILE = os.path.join(_exe_dir, "config.yml")
if not os.path.exists(CONFIG_FILE):
    CONFIG_FILE = os.path.join(os.getcwd(), "config.yml")
MOD_DIR = os.path.dirname(__file__)

general_config = load_yml(os.path.join(MOD_DIR, "configs", "general.yml"))
regex_config = load_yml(os.path.join(MOD_DIR, "configs", "regex.yml"))

IGDBClient.load_precache()

_game_dict = None
_games_cache = None
_download_state = {"running": False, "current": 0, "total": 0, "game": "", "log": []}
_server_start_time = time.time()


def get_user_config():
    if os.path.exists(CONFIG_FILE):
        return load_yml(CONFIG_FILE)
    return {}


def save_user_config(config):
    save_yml(CONFIG_FILE, config)


@app.get("/", response_class=HTMLResponse)
async def index():
    template = Path(os.path.join(MOD_DIR, "templates", "index.html"))
    if template.exists():
        return template.read_text(encoding="utf-8")
    return HTMLResponse("<h1>cart-dl server running</h1>")


def _build_game_cache():
    """Build the sorted game cache from the game dict"""
    global _game_dict, _games_cache
    cfg = get_user_config()
    source_url = cfg.get("source_url", "https://nxbrew.net")

    if _game_dict is None:
        _game_dict = get_game_dict(general_config, regex_config, source_url)

    igdb = IGDBClient(
        client_id=cfg.get("igdb_client_id") or None,
        client_secret=cfg.get("igdb_client_secret") or None,
    )
    filtered = filter_game_dict(_game_dict.copy(), igdb, {
        "igdb_min_rating": cfg.get("igdb_min_rating", DEFAULT_MIN_RATING),
        "igdb_exclude_vn": cfg.get("igdb_exclude_vn", True),
        "igdb_exclude_shovelware": cfg.get("igdb_exclude_shovelware", True),
        "igdb_switch_only": cfg.get("igdb_switch_only", True),
        "igdb_exclude_multi_platform": cfg.get("igdb_exclude_multi_platform", False),
    })

    _games_cache = []
    for url, info in filtered.items():
        _games_cache.append({
            "name": info.get("short_name", info.get("long_name", "")),
            "long_name": info.get("long_name", ""),
            "url": url,
            "rating": info.get("igdb_rating"),
            "has_nsp": info.get("has_nsp", False),
            "has_xci": info.get("has_xci", False),
            "has_update": info.get("has_update", False),
            "has_dlc": info.get("has_dlc", False),
            "igdb_match": info.get("igdb_match", False),
            "other_platforms": info.get("igdb_other_platforms", []),
            "platform": "switch",
        })
    _games_cache.sort(key=lambda g: g["rating"] or 0, reverse=True)


@app.get("/api/games")
async def api_games(request: Request, offset: int = 0, limit: int = 100, sort: str = "rating", order: str = "desc"):
    """Paginated game list. Builds cache on first call."""
    global _games_cache
    if _games_cache is None:
        _build_game_cache()

    games = _games_cache

    # Server-side search
    q = request.query_params.get("q", "").lower()
    if q:
        games = [g for g in games if q in g["name"].lower() or q in g.get("long_name", "").lower()]

    # Sort
    reverse = order == "desc"
    if sort == "name":
        games = sorted(games, key=lambda g: g["name"].lower(), reverse=reverse)
    elif sort == "rating":
        games = sorted(games, key=lambda g: g["rating"] or 0, reverse=reverse)

    total = len(games)
    page = games[offset:offset + limit]

    return JSONResponse({"total": total, "offset": offset, "limit": limit, "games": page})


@app.post("/api/games/refresh")
async def api_refresh(request: Request):
    global _game_dict

    async def generate():
        yield {"event": "status", "data": "scraping"}
        _game_dict = get_game_dict(general_config, regex_config, get_user_config().get("source_url", "https://nxbrew.net"))
        yield {"event": "status", "data": json.dumps({"scraped": len(_game_dict)})}
        yield {"event": "status", "data": "enriching"}
        IGDBClient.load_precache()
        yield {"event": "status", "data": "done"}

    return EventSourceResponse(generate())


@app.post("/api/download")
async def api_download(request: Request):
    global _download_state
    body = await request.json()
    game_urls = body.get("games", [])
    if not game_urls:
        raise HTTPException(400, "No games specified")
    if _download_state["running"]:
        # Auto-reset stale state older than 60s
        if time.time() - _download_state.get("_started", 0) > 60:
            _download_state = {"running": False, "current": 0, "total": 0, "game": "", "log": []}
        else:
            raise HTTPException(409, "Download already in progress")

    _download_state = {"running": True, "current": 0, "total": len(game_urls), "game": "", "log": [], "_started": time.time()}
    cfg = get_user_config()

    def worker():
        global _download_state, _games_cache
        dead_hosts = set()
        shared_jd = None

        # Pre-connect JDownloader once
        try:
            import myjdapi
            jd = myjdapi.Myjdapi()
            jd.set_app_key("nxbrewdl")
            jd.connect(cfg["jd_user"], cfg["jd_pass"])
            shared_jd = jd.get_device(cfg["jd_device"])
            _download_state["log"].append("JD2: connected")
        except Exception as e:
            _download_state["log"].append(f"JD2: FAILED - {e}")

        for i, url in enumerate(game_urls):
            game_name = url.split("/")[-2].replace("-", " ").title()
            _download_state["log"].append(f"[{i+1}/{len(game_urls)}] {game_name}")
            _download_state["current"] = i + 1
            _download_state["game"] = game_name

            # Find alternate URLs for same game across sources
            alt_urls = [url]
            if _games_cache:
                for g in _games_cache:
                    if g["url"] != url and g["name"].lower() == game_name.replace("-", " ").lower():
                        alt_urls.append(g["url"])

            downloaded = False
            for alt_url in alt_urls:
                src = alt_url.split("/")[2] if "//" in alt_url else "?"
                try:
                    import threading as thr
                    result = {"ok": False, "error": "timeout"}
                    def run_dl():
                        try:
                            cfg_copy = dict(cfg)
                            cfg_copy["log_dir"] = None
                            nx = CartDL(to_download={game_name: alt_url}, user_config=cfg_copy,
                                       jd_device=shared_jd, dead_hosts=dead_hosts)
                            nx.run()
                            result["ok"] = True
                        except Exception as e:
                            result["error"] = str(e)[:120]
                    t = thr.Thread(target=run_dl, daemon=True)
                    t.start()
                    t.join(timeout=30)
                    if t.is_alive():
                        _download_state["log"].append(f"  TIMEOUT ({src})")
                    elif result["ok"]:
                        _download_state["log"].append(f"  OK ({src})")
                        downloaded = True
                        break
                    else:
                        _download_state["log"].append(f"  FAIL ({src}): {result['error']}")
                except Exception as e:
                    _download_state["log"].append(f"  FAIL ({src}): {str(e)[:120]}")
            if not downloaded:
                _download_state["log"].append(f"  ALL SOURCES FAILED")
        _download_state["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return JSONResponse({"status": "started", "total": len(game_urls)})


@app.get("/api/download/status")
async def api_download_status():
    return JSONResponse(_download_state)


@app.post("/api/download/reset")
async def api_download_reset():
    global _download_state
    _download_state = {"running": False, "current": 0, "total": 0, "game": "", "log": []}
    return JSONResponse({"status": "reset"})


@app.get("/api/config")
async def api_config():
    cfg = get_user_config()
    safe = {}
    for k, v in cfg.items():
        if any(s in k.lower() for s in ["pass", "secret", "token"]):
            safe[k] = "***" if v else ""
        else:
            safe[k] = v
    safe["has_jd"] = bool(cfg.get("jd_user") and cfg.get("jd_pass"))
    safe["has_igdb"] = bool(cfg.get("igdb_client_id") and cfg.get("igdb_client_secret"))
    return JSONResponse(safe)


@app.post("/api/config")
async def api_config_save(request: Request):
    body = await request.json()
    cfg = get_user_config()
    cfg.update(body)
    save_user_config(cfg)
    return JSONResponse({"status": "ok"})


@app.get("/api/health")
async def api_health():
    cfg = get_user_config()
    return JSONResponse({
        "status": "ok",
        "uptime": round(time.time() - _server_start_time),
        "games_loaded": len(_game_dict) if _game_dict else 0,
        "precache_size": len(IGDBClient._precache) if IGDBClient._precache else 0,
        "source_url": cfg.get("source_url", ""),
        "has_jd": bool(cfg.get("jd_user")),
    })


def run_server(host="127.0.0.1", port=8765, open_browser=True):
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
