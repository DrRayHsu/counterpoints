"""Runs the bot for five simulated weeks against fake Bluesky and GitHub accounts, with no network.

    python simulate.py

Week 1 nobody answers, week 2 readers mostly say ≠, week 3 they split (hardest over Wiener),
week 4 they mostly say =. A reader submits a #found quotation in week 3; it's approved in week 4.
Prints each weekly report and how often each quote was posted.
"""
import json
import random
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bot


class FakeBsky:
    handle, did = "counterpoints.bsky.social", "did:plc:bot"

    def __init__(self):
        self.posts, self.notes, self.reports, self.acks, self.k = {}, [], [], [], 0

    def post_url(self, uri):
        return "https://bsky.app/post/" + uri.rsplit("/", 1)[-1]

    def notifications(self, since):
        return [n for n in self.notes if not since or n["at"] > since]

    def post_stats(self, uris):
        return {u: self.posts[u]["stats"] for u in uris if u in self.posts}

    def send_card(self, text, png, alt, size, sources):
        self.k += 1
        uri = f"at://bot/post/{self.k}"
        self.posts[uri] = {"text": text.build_text(), "stats": {"likes": 0, "reposts": 0, "replies": 0, "quotes": 0}}
        return uri, f"cid{self.k}"

    def send_thread(self, texts):
        self.reports.append([t.build_text() for t in texts])
        return "at://bot/report"

    def reply_to(self, note, text):
        self.acks.append((note["handle"], text))


class FakeGitHub:
    ok = True

    def __init__(self):
        self.items, self.n = {}, 0

    def ensure_labels(self):
        pass

    def open_issue(self, title, body):
        self.n += 1
        self.items[self.n] = {"number": self.n, "title": title, "body": body, "labels": {"found"}, "open": True}

    def issues(self, label):
        return [i for i in self.items.values() if i["open"] and label in i["labels"]]

    def comment(self, number, body, close=False):
        if close:
            self.items[number]["open"] = False


def audience(week, pair, rng):
    """How many readers vote, and which way, for a given week and pair."""
    if week == 1:
        return []
    if week == 2:
        return ["≠"] * rng.randint(2, 5) + ["="] * rng.randint(0, 1)
    if week == 3:
        n = 6 if "wiener" in pair else 2
        return ["=", "≠"] * (n // 2)
    return ["="] * rng.randint(3, 5) + ["≠"] * rng.randint(0, 1)


def main():
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(bot.ROOT / "quotes.json", tmp / "quotes.json")
    bot.DATA, bot.QUOTES_FILE = tmp / "data", tmp / "quotes.json"

    bsky, gh, rng = FakeBsky(), FakeGitHub(), random.Random(1)
    now = datetime(2026, 9, 23, 15, tzinfo=timezone.utc)
    voter = 0
    posted = Counter()
    modes = []
    for step in range(5 * 14 + 1):
        week = step // 14 + 1
        if week == 4 and gh.issues("found") and not gh.issues("approved"):
            issue = gh.issues("found")[0]  # the maintainer checks the wording, then approves
            issue["body"] = issue["body"].replace('"strands": []', '"strands": ["labor", "voice"]')
            issue["labels"].add("approved")
        ia, ib = bot.run(bsky, gh, now)
        posted.update([ia, ib])
        state = json.loads((bot.DATA / "state.json").read_text())
        modes.append(state["mode"])
        uri = f"at://bot/post/{bsky.k}"
        votes = audience(week, (ia, ib), rng)
        for v in votes:
            voter += 1
            at = bot.now_iso(now + timedelta(hours=1, seconds=voter))
            bsky.notes.append({"reason": "reply", "uri": f"at://u{voter}/post/1", "cid": "c", "at": at,
                               "did": f"did:plc:u{voter % 40}", "handle": f"reader{voter % 40}.bsky.social",
                               "text": v, "root": uri, "root_cid": "c", "quoted": None, "links": []})
        bsky.posts[uri]["stats"] = {"likes": len(votes) * 2, "reposts": len(votes) // 3,
                                    "replies": len(votes), "quotes": 0}
        if step == 30:  # a reader submits a quotation
            bsky.notes.append({
                "reason": "mention", "uri": "at://reader7/post/found", "cid": "c",
                "at": bot.now_iso(now + timedelta(hours=2)), "did": "did:plc:reader7",
                "handle": "reader7.bsky.social", "root": None, "root_cid": None, "quoted": None,
                "text": "#found “Our working conditions amount to modern day slavery.” — "
                        "Kenyan data workers, open letter (2024) https://example.org/letter",
                "links": ["https://example.org/letter"]})
        now += timedelta(hours=12)

    for i, r in enumerate(bsky.reports, 1):
        print(f"\n===== report {i} =====")
        for t in r:
            print(f"[{len(t)} chars] {t}\n")
    print("mode by week:", [modes[w * 14] for w in range(5)])
    print("acks sent:", bsky.acks)
    print("most posted:", posted.most_common(6))
    found = [p for p in bsky.posts.values() if "found by" in p["text"]]
    print("posts crediting a reader:", len(found))
    if found:
        print(found[0]["text"])
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
