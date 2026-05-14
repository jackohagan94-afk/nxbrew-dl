import time
import json
import os
from difflib import SequenceMatcher

import requests

# IGDB platform IDs
PLATFORM_SWITCH = 130

# IGDB category: 0 = main game
CATEGORY_MAIN_GAME = 0

# IGDB genre IDs to exclude (shovelware / low-quality filler)
SHOVELWARE_GENRES = {
    9: "Puzzle",
    26: "Quiz/Trivia",
    35: "Card & Board Game",
    30: "Pinball",
    33: "Arcade",
    13: "Simulator",
}

# Visual novel genre ID on IGDB
VISUAL_NOVEL_GENRE = 34

# Notable platform IDs
NOTABLE_PLATFORMS = {
    6: "PC",
    48: "PS4",
    167: "PS5",
    49: "Xbox One",
    169: "Xbox Series",
    130: "Switch",
    3: "Linux",
    14: "Mac",
    39: "iOS",
    34: "Android",
    46: "PS Vita",
    41: "Wii U",
    5: "Wii",
    20: "NDS",
    37: "3DS",
}

# Default minimum rating threshold (0-100)
DEFAULT_MIN_RATING = 50


class IGDBClient:
    """IGDB API client using Twitch OAuth"""

    def __init__(self, client_id, client_secret, cache_file=None, logger=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = 0
        self.logger = logger
        self.cache_file = cache_file
        self.cache = {}
        self._load_cache()

    def _log(self, level, msg):
        if self.logger:
            getattr(self.logger, level)(msg)

    def _load_cache(self):
        if self.cache_file and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.cache = {}

    def _save_cache(self):
        if self.cache_file:
            with open(self.cache_file, "w") as f:
                json.dump(self.cache, f)

    def _authenticate(self):
        """Get Twitch OAuth access token"""
        if self.access_token and time.time() < self.token_expiry - 60:
            return

        resp = requests.post("https://id.twitch.tv/oauth2/token", params={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        })
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.token_expiry = time.time() + data.get("expires_in", 3600)
        self._log("info", "IGDB: authenticated successfully")

    def _api_call(self, endpoint, query):
        """Make an IGDB API call"""
        self._authenticate()
        resp = requests.post(
            f"https://api.igdb.com/v4/{endpoint}",
            headers={
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {self.access_token}",
            },
            data=query,
        )
        if resp.status_code == 429:
            self._log("warning", "IGDB: rate limited, waiting 1s")
            time.sleep(1)
            return self._api_call(endpoint, query)
        resp.raise_for_status()
        return resp.json()

    def search_game(self, name):
        """Search IGDB for a game by name, return best match

        Args:
            name (str): Game name to search

        Returns:
            dict or None: Game info with rating, genres, platforms
        """
        cache_key = name.lower().strip()
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            # Try exact name search first
            results = self._api_call("games", (
                f'search "{name}";'
                "fields name,rating,total_rating,aggregated_rating,"
                "genres,platforms,category,first_release_date;"
                "limit 10;"
            ))

            # If no results, try a shorter search (first 3-4 words)
            if not results:
                words = name.split()
                if len(words) > 4:
                    shorter = " ".join(words[:4])
                    results = self._api_call("games", (
                        f'search "{shorter}";'
                        "fields name,rating,total_rating,aggregated_rating,"
                        "genres,platforms,category,first_release_date;"
                        "limit 10;"
                    ))
        except Exception as e:
            self._log("warning", f"IGDB search failed for '{name}': {e}")
            return None

        if not results:
            self.cache[cache_key] = None
            self._save_cache()
            return None

        # Find best match by name similarity, preferring rated results on Switch
        best_match = None
        best_score = 0
        search_lower = name.lower()
        for game in results:
            game_name = game.get("name", "")
            score = SequenceMatcher(None, search_lower, game_name.lower()).ratio()

            # Bonus for exact name match
            if game_name.lower() == search_lower:
                score += 0.5

            # Bonus for having a rating
            has_rating = game.get("rating") or game.get("total_rating")
            if has_rating:
                score += 0.1

            # Bonus for Switch platform
            if PLATFORM_SWITCH in game.get("platforms", []):
                score += 0.1

            if score > best_score:
                best_score = score
                best_match = game

        if best_match and best_score < 0.35:
            best_match = None

        self.cache[cache_key] = best_match
        self._save_cache()
        return best_match

    def get_game_rating(self, name):
        """Get rating for a game, return 0-100 or None"""
        game = self.search_game(name)
        if not game:
            return None

        # Prefer total_rating, fall back to rating, then aggregated_rating
        ratings = []
        for key in ["total_rating", "rating", "aggregated_rating"]:
            val = game.get(key)
            if val and isinstance(val, (int, float)):
                ratings.append(round(val))

        return max(ratings) if ratings else None

    def get_game_genres(self, name):
        """Get genre IDs for a game"""
        game = self.search_game(name)
        return game.get("genres", []) if game else []

    def has_switch_release(self, name):
        """Check if game has a Nintendo Switch release"""
        game = self.search_game(name)
        if not game:
            return False
        return PLATFORM_SWITCH in game.get("platforms", [])

    def is_visual_novel(self, name):
        """Check if game is a visual novel"""
        genres = self.get_game_genres(name)
        return VISUAL_NOVEL_GENRE in genres

    def is_shovelware(self, name):
        """Check if game matches shovelware genres"""
        genres = self.get_game_genres(name)
        for gid in genres:
            if gid in SHOVELWARE_GENRES:
                return True
        return False

    def get_game_info(self, name):
        """Get complete game info from IGDB

        Returns:
            dict with keys: rating, genres, genre_names, is_vn, is_shovelware, on_switch
        """
        game = self.search_game(name)
        if not game:
            return None

        rating = None
        for key in ["total_rating", "rating", "aggregated_rating"]:
            val = game.get(key)
            if val and isinstance(val, (int, float)):
                rating = round(val)
                break

        genre_ids = game.get("genres", [])
        platform_ids = game.get("platforms", [])

        genre_names = []
        is_vn = False
        is_shovelware = False
        for gid in genre_ids:
            if gid == VISUAL_NOVEL_GENRE:
                is_vn = True
            if gid in SHOVELWARE_GENRES:
                is_shovelware = True
                genre_names.append(SHOVELWARE_GENRES[gid])

        # Map platform IDs to names
        other_platforms = []
        for pid in platform_ids:
            if pid != PLATFORM_SWITCH and pid in NOTABLE_PLATFORMS:
                other_platforms.append(NOTABLE_PLATFORMS[pid])

        return {
            "rating": rating,
            "total_rating": game.get("total_rating"),
            "genre_ids": genre_ids,
            "genres": genre_names,
            "is_visual_novel": is_vn,
            "is_shovelware": is_shovelware,
            "on_switch": PLATFORM_SWITCH in platform_ids,
            "other_platforms": other_platforms,
            "igdb_name": game.get("name"),
        }


def filter_game_dict(game_dict, igdb_client, config):
    """Filter and score scraped games using IGDB data

    Args:
        game_dict (dict): Dictionary of games from scraper
        igdb_client (IGDBClient): Authenticated IGDB client
        config (dict): Filtering config with keys:
            - igdb_min_rating (int): Minimum rating threshold (default 50)
            - igdb_exclude_vn (bool): Exclude visual novels
            - igdb_exclude_shovelware (bool): Exclude shovelware genres
            - igdb_switch_only (bool): Only include games with Switch release
            - igdb_exclude_multi_platform (bool): Exclude games on other platforms

    Returns:
        dict: Filtered game_dict with added IGDB metadata
    """
    min_rating = config.get("igdb_min_rating", DEFAULT_MIN_RATING)
    exclude_vn = config.get("igdb_exclude_vn", True)
    exclude_shovelware = config.get("igdb_exclude_shovelware", True)
    switch_only = config.get("igdb_switch_only", True)
    exclude_multi = config.get("igdb_exclude_multi_platform", False)

    enriched = {}
    filtered_count = 0

    for url, info in game_dict.items():
        short_name = info["short_name"]
        igdb_info = igdb_client.get_game_info(short_name)

        if igdb_info is None:
            # No IGDB match - keep the game but mark as unrated
            info["igdb_rating"] = None
            info["igdb_match"] = False
            enriched[url] = info
            continue

        info["igdb_rating"] = igdb_info["rating"]
        info["igdb_match"] = True
        info["igdb_genres"] = igdb_info["genres"]
        info["igdb_name"] = igdb_info["igdb_name"]
        info["igdb_other_platforms"] = igdb_info.get("other_platforms", [])

        # Apply filters
        if exclude_vn and igdb_info["is_visual_novel"]:
            filtered_count += 1
            continue

        if exclude_shovelware and igdb_info["is_shovelware"]:
            filtered_count += 1
            continue

        if switch_only and not igdb_info["on_switch"]:
            filtered_count += 1
            continue

        if exclude_multi and len(igdb_info.get("other_platforms", [])) > 0:
            filtered_count += 1
            continue

        if min_rating > 0 and igdb_info["rating"] is not None and igdb_info["rating"] < min_rating:
            filtered_count += 1
            continue

        enriched[url] = info

    if hasattr(igdb_client, '_log'):
        igdb_client._log("info", f"IGDB: filtered {filtered_count} games, {len(enriched)} remaining")

    return enriched
