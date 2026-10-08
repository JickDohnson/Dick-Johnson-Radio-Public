"""Post a GitHub release to Discord: title, link, the release notes and the download links.

Run by .github/workflows/discord-release.yml. Standard library only.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com/repos/" + os.environ.get("GITHUB_REPOSITORY", "JickDohnson/Dick-Johnson-Radio-Public")
LOGO = "https://raw.githubusercontent.com/JickDohnson/Dick-Johnson-Radio-Public/main/logo.png"
COLOR = 0xF97316  # the app's orange
MAX_NOTES = 3600  # Discord allows 4096 characters in an embed's description; leave room for the "more" link


def github(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "release-to-discord"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def the_release():
    """The release from the event, or (run by hand) the tag asked for, or the latest."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.load(open(path, encoding="utf-8")) if path and os.path.exists(path) else {}
    if event.get("release"):
        # re-read it: the event can be sent before every file has finished uploading
        return github(f"/releases/{event['release']['id']}")
    tag = (os.environ.get("TAG") or "").strip()
    return github(f"/releases/tags/{tag}") if tag else github("/releases/latest")


def discord_markdown(body):
    """GitHub release notes, tidied for a Discord embed."""
    body = (body or "").replace("\r\n", "\n")
    body = re.split(r"\n\*\*SHA-256\*\*", body)[0]  # checksums: on the release page, not in the channel
    body = re.split(r"\n## Download\b", body)[0]  # downloads get their own field below
    lines = []
    for line in body.split("\n"):
        heading = re.match(r"#{1,6}\s+(.*)", line)
        lines.append(f"**{heading.group(1).strip()}**" if heading else line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def size_text(n):
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def main():
    # one webhook URL per channel: the secret can hold several, one per line (or separated by spaces or commas)
    hooks = [h for h in re.split(r"[\s,]+", os.environ.get("DISCORD_WEBHOOK", "")) if h.startswith("http")]
    if not hooks:
        sys.exit("No DISCORD_WEBHOOK secret: add the channel's webhook URL in the repo's "
                 "Settings > Secrets and variables > Actions.")
    rel = the_release()
    if rel.get("draft"):
        print("Draft release: not posting.")
        return
    name = rel.get("name") or rel["tag_name"]
    url = rel["html_url"]
    notes = discord_markdown(rel.get("body"))
    if len(notes) > MAX_NOTES:
        notes = notes[:MAX_NOTES].rsplit("\n", 1)[0] + f"\n…\n[Read the full notes]({url})"
    embed = {"title": f"{name} is out", "url": url, "description": notes or f"[See what's new]({url})",
             "color": COLOR, "thumbnail": {"url": LOGO}, "timestamp": rel.get("published_at")}
    assets = [a for a in rel.get("assets", []) if a.get("state", "uploaded") == "uploaded"]
    if assets:
        order = {".zip": 0, ".exe": 1}
        assets.sort(key=lambda a: order.get(os.path.splitext(a["name"])[1].lower(), 2))
        lines = []
        for a in assets:
            what = ("installer: unzip and run it" if a["name"].lower().endswith(".zip") else
                    "no install needed" if a["name"].lower().endswith(".exe") else "")
            lines.append(f"[{a['name']}]({a['browser_download_url']}) · {size_text(a['size'])}"
                         + (f" · {what}" if what else ""))
        embed["fields"] = [{"name": "Download", "value": "\n".join(lines)[:1024]}]
    embed["footer"] = {"text": "Already on 1.1 or later? The app offers this update by itself."}
    payload = {"username": "Dick Johnson Radio", "avatar_url": LOGO, "embeds": [embed],
               "allowed_mentions": {"parse": []}}  # (notes never ping @everyone or anyone else)
    failed = 0
    for n, hook in enumerate(hooks, 1):  # (one channel failing doesn't stop the others)
        req = urllib.request.Request(hook, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json",
                                              # (Discord's firewall turns away Python's default user agent)
                                              "User-Agent": "DiscordBot (https://github.com/JickDohnson, 1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print(f"Posted {name} to Discord channel {n} of {len(hooks)} ({r.status}).")
        except urllib.error.HTTPError as e:
            failed += 1
            print(f"Channel {n} of {len(hooks)}: Discord said {e.code}: "
                  f"{e.read().decode('utf-8', 'replace')[:500]}")
        except urllib.error.URLError as e:
            failed += 1
            print(f"Channel {n} of {len(hooks)}: couldn't reach Discord: {e.reason}")
    if failed:
        sys.exit(f"{failed} of {len(hooks)} channel(s) didn't get the post.")


if __name__ == "__main__":
    main()
