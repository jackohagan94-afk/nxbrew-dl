import requests


def check_github_version():
    """Check cart-dl version on GitHub. Returns version and associated URL"""

    url = "https://api.github.com/repos/bbtufty/cart-dl/releases/latest"
    r = requests.get(url)

    json = r.json()

    # Pull out version and URL
    version = json["name"]
    github_url = json["html_url"]

    return version, github_url
