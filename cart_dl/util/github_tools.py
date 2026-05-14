import requests


def check_github_version():
    """Check for new versions on GitHub. Returns version and associated URL"""

    url = "https://api.github.com/repos/bbtufty/nxbrew-dl/releases/latest"
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        version = data["name"]
        github_url = data["html_url"]
        return version, github_url
    except Exception:
        return "0.0.0", ""
