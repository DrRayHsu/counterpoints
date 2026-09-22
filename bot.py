"""Counterpoints: two quotations at a time on Bluesky, paired by rules its readers retrain in public.

Each run:
  1. adds any submissions you've approved on GitHub to quotes.json
  2. reads new replies, mentions and quote-posts: votes (= / ≠) and #found submissions
  3. once a week, reads the mood, picks next week's mode, and posts a report explaining it
  4. posts the next pair, weighted toward what divides readers

Usage:
  python bot.py              # one run (needs BSKY_HANDLE, BSKY_APP_PASSWORD; GITHUB_TOKEN for submissions)
  python bot.py --dry-run    # render the next card to out/ and print the post text; no network
  python bot.py --check      # log in to Bluesky and GitHub and report what works; posts nothing
"""
import argparse
import hashlib
import json
import os
import random
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atproto import client_utils

import logic
import render

ROOT = Path(__file__).parent
DATA = ROOT / "data"
QUOTES_FILE = ROOT / "quotes.json"
CONFIG = json.loads((ROOT / "config.json").read_text())

MOOD_READ = {
    "quiet": "Almost no one voted.",
    "unclear": "You replied, but few of you voted.",
    "objecting": "Most of you said the pairings break.",
    "agreeing": "Most of you said the pairings hold.",
    "contested": "You split.",
}
MODE_DESC = {
    "random": "anything with anything.",
    "cross-era": "old against new, weighted toward what divided you.",
    "same-strand": "old against new, only where both quotes make the same argument.",
    "cross-strand": "old against new, only where the quotes share no argument.",
    "curated": "a list chosen by hand.",
}
VOTE_HINT = "Reply = if the pairing holds, ≠ if it breaks."


def now_iso(now):
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def load_quotes():
    return json.loads(QUOTES_FILE.read_text())


def save_quotes(qs):
    QUOTES_FILE.write_text(json.dumps(qs, indent=2, ensure_ascii=False) + "\n")


def fits(tb):
    return len(tb.build_text()) <= 300

# ---------- 1. approved submissions ----------

def import_approved(gh, now):
    if not gh.ok:
        return []
    qs = load_quotes()
    ids = {q["id"] for q in qs}
    added = []
    for issue in gh.issues("approved"):
        m = re.search(r"```json\s*(\{.*?\})\s*```", issue.get("body") or "", re.S)
        try:
            q = json.loads(m.group(1))
            missing = [k for k in ("id", "year", "text", "attribution", "short", "url") if not q.get(k) and q.get(k) != 0]
            if missing:
                raise ValueError("missing " + ", ".join(missing))
            q["year"] = int(q["year"])
        except Exception as e:  # noqa: BLE001
            gh.comment(issue["number"], f"Couldn't add this yet: {e}. Fix the JSON block and re-apply `approved`.")
            continue
        base, k = q["id"], 2
        while q["id"] in ids:
            q["id"], k = f"{base}-{k}", k + 1
        q["added"] = now_iso(now)
        qs.append(q)
        ids.add(q["id"])
        added.append(q)
        gh.comment(issue["number"], f"Added to the corpus as `{q['id']}`.", close=True)
    if added:
        save_quotes(qs)
    return added

# ---------- 2. reading responses ----------

def voter_id(did):
    salt = os.environ.get("VOTE_SALT") or os.environ.get("BSKY_APP_PASSWORD", "")
    return hashlib.sha256((salt + did).encode()).hexdigest()[:16]


def submission_issue(n, bsky):
    q = logic.parse_submission(n["text"], n["links"])
    q["found_by"] = {"handle": n["handle"], "did": n["did"]}
    link = f"https://bsky.app/profile/{n['handle']}/post/{n['uri'].rsplit('/', 1)[-1]}"
    quoted = "\n".join("> " + line for line in n["text"].splitlines())
    body = (f"Submitted by @{n['handle']} on Bluesky: {link}\n\n{quoted}\n\n"
            "**Before approving:** check the wording against the original source, fix the JSON below "
            "(`id`, `year`, `text`, `attribution`, `short`, `url`) and set `strands` from: labor, status, "
            "master, naming, voice. Then add the `approved` label. To reject, close the issue.\n\n"
            f"```json\n{json.dumps(q, indent=2, ensure_ascii=False)}\n```\n")
    title = f"#found from @{n['handle']}: {q['text'][:60]}"
    return title, body


def harvest(bsky, gh, state, log, now):
    notes = bsky.notifications(state.get("notif_seen"))
    by_uri = {p["uri"]: p for p in log}
    seen = set(state.setdefault("submissions_seen", []))
    for n in notes:
        state["notif_seen"] = max(state.get("notif_seen") or "", n["at"])
        if logic.is_submission(n["text"]):
            if n["uri"] in seen:
                continue
            seen.add(n["uri"])
            state["submissions_seen"].append(n["uri"])
            if gh.ok:
                gh.open_issue(*submission_issue(n, bsky))
                if CONFIG.get("ack_submissions", True):
                    bsky.reply_to(n, "Thank you. This is waiting for review; if it's added, "
                                     "you'll be credited whenever it's posted.")
            continue
        target = n["root"] if n["reason"] in ("reply", "mention") else n["quoted"]
        vote = logic.parse_vote(n["text"])
        if target in by_uri and vote:
            by_uri[target].setdefault("votes", {})[voter_id(n["did"])] = vote  # latest vote per account wins
    state["submissions_seen"] = state["submissions_seen"][-500:]

    cutoff = now_iso(now - timedelta(days=30))
    recent = [p["uri"] for p in log if p["at"] >= cutoff]
    for uri, s in bsky.post_stats(recent).items():
        by_uri[uri].update(s)

# ---------- 3. weekly report ----------

def report(bsky, gh, state, log, quotes, now):
    since = state["last_report"]
    window = [p for p in log if p["at"] >= since]
    mood, s = logic.read_mood(window, CONFIG)
    old = state["mode"]
    new = CONFIG.get("mode_override") or (old if mood == "unclear" else CONFIG["mood_modes"][mood])
    nxt = ("So I'll keep going: " if new == old else "So next week: ") + MODE_DESC[new]

    posts = []
    t = client_utils.TextBuilder().text(
        f"How you changed me this week.\n\n{len(window)} pairs. {s['holds']} of you said = (holds), "
        f"{s['breaks']} said ≠ (breaks). {s['engagement']} likes, reposts, replies and quotes.\n\n"
        f"{MOOD_READ[mood]} {nxt}")
    posts.append(t)

    top = logic.most_contested(window)
    if top and all(i in quotes for i in top["pair"]):
        a, b = (quotes[i] for i in top["pair"])
        c = Counter(top["votes"].values())
        t = (client_utils.TextBuilder().text("What split you most: ")
             .link(f"{a['short']} with {b['short']}", bsky.post_url(top["uri"]))
             .text(f" ({c['holds']} =, {c['breaks']} ≠). Quotes and pairs that divide you "
                   "come back more often."))
        posts.append(t)

    new_quotes = [q for q in quotes.values() if q.get("found_by") and q.get("added", "") > since]
    pending = len(gh.issues("found")) - len(gh.issues("approved")) if gh.ok else 0
    t = client_utils.TextBuilder()
    if new_quotes:
        t.text("New in the corpus: ")
        for i, q in enumerate(new_quotes[:3]):
            t.text(("; " if i else "") + f"{q['short']}, found by ")
            t.mention("@" + q["found_by"]["handle"], q["found_by"]["did"])
        t.text(". ")
    if pending > 0:
        t.text(f"{pending} waiting for review. ")
    t.text("To add a quotation, reply or post: #found “the exact words” — source (year) and a link.")
    if not fits(t):
        t = client_utils.TextBuilder().text(
            f"{len(new_quotes)} new in the corpus. To add a quotation: #found “the exact words” — source (year) and a link.")
    posts.append(t)

    posts = [p for p in posts if fits(p)]
    uri = bsky.send_thread(posts)
    state.setdefault("moods", []).append({"at": now_iso(now), "mood": mood, "mode": new, **s, "uri": uri})
    state["mode"], state["last_report"] = new, now_iso(now)
    return mood, new

# ---------- 4. posting ----------

def compose(a, b):
    t = client_utils.TextBuilder().text(f"{a['short']}\n{b['short']}")
    for q in (a, b):
        if q.get("found_by"):
            t.text("\nfound by ").mention("@" + q["found_by"]["handle"], q["found_by"]["did"])
    t.text("\n\n" + VOTE_HINT)
    src = client_utils.TextBuilder().text("Sources: ").link(a["short"], a["url"]).text(" · ").link(b["short"], b["url"])
    return t, src


def post_pair(bsky, state, log, quotes, now):
    rng = random.Random(f"{CONFIG['seed']}-{state['n']}")
    ia, ib = logic.pick(quotes, log, state["mode"], CONFIG, rng, now)
    a, b = quotes[ia], quotes[ib]
    png, size = render.card(a, b)
    text, src = compose(a, b)
    uri, cid = bsky.send_card(text, png, render.alt_text(a, b), size, src)
    log.append({"n": state["n"], "uri": uri, "cid": cid, "pair": [ia, ib], "at": now_iso(now),
                "mode": state["mode"], "votes": {}})
    state["n"] += 1
    return ia, ib

# ---------- run ----------

def run(bsky, gh, now):
    state = load("state.json", {"n": 0, "mode": CONFIG["start_mode"], "notif_seen": None, "last_report": None})
    log = load("log.json", [])
    if gh.ok:
        gh.ensure_labels()

    import_approved(gh, now)
    harvest(bsky, gh, state, log, now)
    save("state.json", state), save("log.json", log)

    quotes = {q["id"]: q for q in load_quotes()}
    if state["last_report"] is None:
        state["last_report"] = now_iso(now)  # start the first week's clock
    elif now - datetime.fromisoformat(state["last_report"].replace("Z", "+00:00")) >= timedelta(days=CONFIG["report_every_days"]):
        report(bsky, gh, state, log, quotes, now)
    save("state.json", state)

    pair = post_pair(bsky, state, log, quotes, now)
    save("state.json", state), save("log.json", log)
    return pair


def check():
    from services import Bsky, GitHub
    ok = True
    try:
        b = Bsky(os.environ["BSKY_HANDLE"], os.environ["BSKY_APP_PASSWORD"])
        b.notifications(None)
        print(f"Bluesky: logged in as {b.handle}, notifications readable")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"Bluesky: FAILED ({type(e).__name__}: {e}). Check the BSKY_HANDLE and BSKY_APP_PASSWORD secrets.")
    gh = GitHub()
    if not gh.ok:
        print("GitHub: no token, so #found submissions will be skipped")
    else:
        try:
            gh.ensure_labels()
            gh.issues("found")
            print(f"GitHub: issues readable and writable on {gh.repo}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"GitHub: FAILED ({e}). Turn on read-and-write workflow permissions and make sure Issues are enabled.")
    print("VOTE_SALT: set" if os.environ.get("VOTE_SALT") else "VOTE_SALT: not set (falls back to the app password)")
    if not ok:
        raise SystemExit(1)
    print("All set. Nothing was posted.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    if args.dry_run:
        state = load("state.json", {"n": 0, "mode": CONFIG["start_mode"]})
        log = load("log.json", [])
        quotes = {q["id"]: q for q in load_quotes()}
        ia, ib = logic.pick(quotes, log, state["mode"], CONFIG, random.Random(f"{CONFIG['seed']}-{state['n']}"), now)
        png, _ = render.card(quotes[ia], quotes[ib])
        (ROOT / "out").mkdir(exist_ok=True)
        (ROOT / "out" / f"{ia}__{ib}.png").write_bytes(png)
        text, src = compose(quotes[ia], quotes[ib])
        print(f"mode: {state['mode']}\n---\n{text.build_text()}\n---\n{src.build_text()}")
        return

    from services import Bsky, GitHub
    if args.check:
        return check()
    bsky = Bsky(os.environ["BSKY_HANDLE"], os.environ["BSKY_APP_PASSWORD"])
    ia, ib = run(bsky, GitHub(), now)
    print(f"posted {ia} × {ib}")


if __name__ == "__main__":
    main()
