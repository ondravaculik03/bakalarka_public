import logging

import requests

GITHUB_REPO = "ondravaculik03/bakalarka_public"


def get_latest_github_version():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("tag_name", None)
        else:
            logging.warning(f"GitHub API returned {resp.status_code}")
    except Exception as e:
        logging.warning(f"Failed to check GitHub release: {e}")
    return None


def is_newer_version(current, latest):
    def parse(v):
        return [int(x) for x in v.strip("v").split(".") if x.isdigit()]

    return parse(latest) > parse(current)


def check_for_update(current_version):
    latest = get_latest_github_version()
    if latest and is_newer_version(current_version, latest):
        logging.info(f"Nová verze dostupná: {latest}. Aktuální: {current_version}")
        # Zde můžeš spustit update (stažení a nahrazení .exe)
    else:
        logging.info("Aplikace je aktuální.")
