# NXBrew-dl

[![](https://img.shields.io/pypi/v/nxbrew-dl.svg?label=PyPI&style=flat-square)](https://pypi.org/pypi/nxbrew-dl/)
[![](https://img.shields.io/pypi/pyversions/nxbrew-dl.svg?label=Python&color=yellow&style=flat-square)](https://pypi.org/pypi/nxbrew-dl/)
[![Docs](https://readthedocs.org/projects/nxbrew-dl/badge/?version=latest&style=flat-square)](https://nxbrew-dl.readthedocs.io/en/latest/)
[![Actions](https://img.shields.io/github/actions/workflow/status/bbtufty/nxbrew-dl/build.yaml?branch=main&style=flat-square)](https://github.com/bbtufty/nxbrew-dl/actions)
[![License](https://img.shields.io/badge/license-GNUv3-blue.svg?label=License&style=flat-square)](LICENSE)

NXBrew-dl is intended to be an easy-to-user interface to download ROMs, DLC and update files for NSP. It does so via
a GUI interface, allowing users to download items in bulk and keeping things up-to-date.

As of now, this is in extremely early development. It will parse and download many ROMs, and by default will only
grab ROMs from either the USA or Europe (USA preferred) that are marked as having English language releases.

## Installation

We recommend using the executable version. You can grab the latest release from the [releases page](https://github.com/bbtufty/nxbrew-dl/releases). Place the 
.exe wherever you want, and double-click to load.

Alternatively, you can install via pip:
```shell
pip install nxbrew-dl
```
Or download the latest from GitHub:
```shell
git clone https://github.com/bbtufty/nxbrew-dl.git
cd nxbrew-dl
pip install -e . -r requirements.txt
```
If you use these versions, you can then run from the terminal as:
```shell
nxbrew-dl
```

## 

To get things set up, see the [documentation](https://nxbrew-dl.readthedocs.io/en/latest/).

We encourage users to open [issues](https://github.com/bbtufty/nxbrew-dl/issues>) as and where they find them.

## Recent Fixes (2026-05-14)

### Cloudflare/Anti-Bot Bypass
The scraper now uses `curl_cffi` with TLS fingerprint impersonation instead of plain `requests`. This bypasses Cloudflare and adblock detection on nxbrew domains. Impersonation profiles are auto-selected per domain:
- `nxbrew.net` → Chrome
- `nxbrew.me` → Safari 15.5

### Multi-Domain Game Index Aggregation
The site migrated from `nxbrew.me` to `nxbrew.net`, but not all games were migrated. The scraper now aggregates games from both:
- Primary: `{nxbrew_url}/game-index/` (AlphaListing plugin format, ~1293 games)
- Alternative: `nxbrew.me/games/` (entry-content list format, ~168 additional games)
- **Total: ~1,461 games**

### Updated Index Parsing
The nxbrew.net site replaced its old `div#easyindex-index > li` structure with a WordPress AlphaListing plugin (`div.az-listing > div.letter-section > ul.az-columns > li > a`). The parser now supports both formats with automatic fallback.

### Known Limitations
- `nxbrew.me` uses JavaScript-obfuscated download buttons (`onclick="downloadFile(n)"`) - individual game pages on this domain cannot be scraped. Only games hosted on `nxbrew.net` support full end-to-end download.
- URL validation in the GUI now uses `curl_cffi` with impersonation for connectivity checks.

### Configuration
Set `nxbrew_url` in `config.yml` to `https://nxbrew.net`. Alternative domains are configured in `nxbrew_dl/util/html_tools.py` (`ALTERNATIVE_INDICES` list).