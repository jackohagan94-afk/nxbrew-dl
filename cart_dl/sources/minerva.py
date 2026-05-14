import os, subprocess, tempfile, urllib.parse
from pathlib import Path
import json

MINERVA_BASE = "https://minerva-archive.org"
MINERVA_ASSETS = f"{MINERVA_BASE}/assets/Minerva_Myrient_v0.3"

PLATFORM_COLLECTIONS = {
    "switch": "No-Intro/Nintendo - Nintendo Switch",
    "wiiu": "Redump/Nintendo - Wii U - WUX",
    "wii": "Redump/Nintendo - Wii - NKit RVZ [zstd-19-128k]",
    "gc": "Redump/Nintendo - GameCube - NKit RVZ [zstd-19-128k]",
    "3ds": "No-Intro/Nintendo - Nintendo 3DS (Decrypted)",
    "ds": "No-Intro/Nintendo - Nintendo DS (Decrypted)",
    "gba": "No-Intro/Nintendo - Game Boy Advance",
    "n64": "No-Intro/Nintendo - Nintendo 64 (BigEndian)",
    "snes": "No-Intro/Nintendo - Super Nintendo Entertainment System",
    "nes": "No-Intro/Nintendo - Nintendo Entertainment System (Headered)",
    "ps4": "Redump/Sony - PlayStation 4",
    "ps3": "Redump/Sony - PlayStation 3",
    "ps2": "Redump/Sony - PlayStation 2",
    "ps1": "Redump/Sony - PlayStation",
    "psp": "Redump/Sony - PlayStation Portable",
    "xbox360": "Redump/Microsoft - Xbox 360",
    "xbox": "Redump/Microsoft - Xbox",
    "dc": "Redump/Sega - Dreamcast",
    "genesis": "No-Intro/Sega - Mega Drive - Genesis",
}


def bdecode(data, idx=0):
    if data[idx:idx+1] == b'd':
        idx += 1; d = {}
        while data[idx:idx+1] != b'e':
            k, idx = bdecode(data, idx)
            v, idx = bdecode(data, idx)
            d[k] = v
        return d, idx + 1
    elif data[idx:idx+1] == b'l':
        idx += 1; lst = []
        while data[idx:idx+1] != b'e':
            v, idx = bdecode(data, idx); lst.append(v)
        return lst, idx + 1
    elif data[idx:idx+1] == b'i':
        end = data.index(b'e', idx)
        return int(data[idx+1:end]), end + 1
    else:
        colon = data.index(b':', idx)
        n = int(data[idx:colon])
        start = colon + 1
        return data[start:start+n], start + n


class MinervaSource:
    def __init__(self, download_dir, aria2c_path="aria2c.exe"):
        self.download_dir = download_dir
        self.aria2c_path = aria2c_path
        self.torrent_cache = {}

    def get_torrent_url(self, platform):
        collection = PLATFORM_COLLECTIONS.get(platform)
        if not collection:
            return None
        encoded = urllib.parse.quote(f"Minerva_Myrient - {collection}.torrent")
        return f"{MINERVA_ASSETS}/{encoded}"

    def fetch_torrent(self, platform):
        url = self.get_torrent_url(platform)
        if not url:
            return None
        if platform in self.torrent_cache:
            return self.torrent_cache[platform]
        from curl_cffi import requests
        r = requests.get(url, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            return None
        self.torrent_cache[platform] = r.content
        return r.content

    def parse_torrent_files(self, torrent_data):
        t, _ = bdecode(torrent_data)
        info = t.get(b'info', {})
        files = []
        if b'files' in info:
            for f in info[b'files']:
                path = b'/'.join(f[b'path']).decode('utf-8', errors='replace')
                size = f.get(b'length', 0)
                if path.startswith('.pad/'):
                    continue
                files.append((path, size))
        else:
            name = info.get(b'name', b'').decode('utf-8', errors='replace')
            size = info.get(b'length', 0)
            files.append((name, size))
        return files

    def find_file(self, torrent_data, game_name, extensions=None):
        if extensions is None:
            extensions = ['.rvz', '.wux', '.iso', '.3ds', '.nds', '.gba', '.n64', '.z64', '.sfc', '.nes', '.pkg', '.bin', '.cue']
        files = self.parse_torrent_files(torrent_data)
        search = game_name.lower().replace(' ', '')
        for path, size in files:
            basename = os.path.basename(path).lower()
            basename_clean = basename.replace(' ', '').replace('_', '').replace('-', '')
            if any(ext in basename for ext in extensions):
                if search in basename_clean or basename_clean in search:
                    return path, size
        return None, None

    def download_file(self, torrent_data, file_path, output_dir):
        tmp = tempfile.NamedTemporaryFile(suffix='.torrent', delete=False)
        tmp.write(torrent_data)
        tmp.close()
        os.makedirs(output_dir, exist_ok=True)
        cmd = [self.aria2c_path, '--dir', output_dir, '--select-file', file_path, tmp.name]
        subprocess.run(cmd, capture_output=True)
        os.unlink(tmp.name)
