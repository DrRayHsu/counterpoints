"""Thin wrappers around Bluesky and GitHub, so the rest of the bot can be tested with fakes."""
import os

import requests


def _g(obj, *path):
    """Walk attributes or dict keys; returns None if any step is missing."""
    for key in path:
        if obj is None:
            return None
        obj = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return obj


class Bsky:
    def __init__(self, handle, password):
        from atproto import Client
        self.c = Client()
        self.c.login(handle, password)
        self.did = self.c.me.did
        self.handle = handle

    def post_url(self, uri):
        return f"https://bsky.app/profile/{self.handle}/post/{uri.rsplit('/', 1)[-1]}"

    def notifications(self, since):
        """Replies, mentions and quote-posts newer than `since` (ISO time), oldest first."""
        out, cursor = [], None
        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            r = self.c.app.bsky.notification.list_notifications(params=params)
            stop = False
            for n in r.notifications:
                if since and n.indexed_at <= since:
                    stop = True
                    break
                if n.reason not in ("reply", "mention", "quote") or n.author.did == self.did:
                    continue
                rec = n.record
                links = [f.uri for fac in (_g(rec, "facets") or []) for f in (fac.features or []) if _g(f, "uri")]
                ext = _g(rec, "embed", "external", "uri")
                if ext:
                    links.append(ext)
                out.append({
                    "reason": n.reason, "uri": n.uri, "cid": n.cid, "at": n.indexed_at,
                    "did": n.author.did, "handle": n.author.handle,
                    "text": _g(rec, "text") or "",
                    "root": _g(rec, "reply", "root", "uri"),
                    "root_cid": _g(rec, "reply", "root", "cid"),
                    "quoted": _g(rec, "embed", "record", "uri") or _g(rec, "embed", "record", "record", "uri"),
                    "links": links,
                })
            cursor = r.cursor
            if stop or not cursor:
                break
        return list(reversed(out))

    def post_stats(self, uris):
        stats = {}
        for i in range(0, len(uris), 25):
            for p in self.c.get_posts(uris=uris[i:i + 25]).posts:
                stats[p.uri] = {"likes": p.like_count or 0, "reposts": p.repost_count or 0,
                                "replies": max((p.reply_count or 0) - 1, 0),  # minus our own sources reply
                                "quotes": p.quote_count or 0}
        return stats

    def send_card(self, text, png, alt, size, sources):
        from atproto import models
        main = self.c.send_image(text=text, image=png, image_alt=alt,
                                 image_aspect_ratio=models.AppBskyEmbedDefs.AspectRatio(width=size[0], height=size[1]))
        ref = models.create_strong_ref(main)
        self.c.send_post(sources, reply_to=models.AppBskyFeedPost.ReplyRef(parent=ref, root=ref))
        return main.uri, main.cid

    def send_thread(self, texts):
        from atproto import models
        root = parent = None
        for t in texts:
            reply = models.AppBskyFeedPost.ReplyRef(parent=parent, root=root) if root else None
            r = self.c.send_post(t, reply_to=reply)
            parent = models.create_strong_ref(r)
            root = root or parent
        return root.uri if root else None

    def reply_to(self, note, text):
        from atproto import models
        parent = models.ComAtprotoRepoStrongRef.Main(uri=note["uri"], cid=note["cid"])
        root = (models.ComAtprotoRepoStrongRef.Main(uri=note["root"], cid=note["root_cid"])
                if note.get("root") else parent)
        self.c.send_post(text, reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent, root=root))


class GitHub:
    """Submissions become issues. Label one `approved` and the bot adds it to quotes.json."""

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.repo = os.environ.get("GITHUB_REPOSITORY")
        self.ok = bool(self.token and self.repo)

    def _req(self, method, path, **kw):
        r = requests.request(method, f"https://api.github.com/repos/{self.repo}{path}", timeout=30,
                             headers={"Authorization": f"Bearer {self.token}",
                                      "Accept": "application/vnd.github+json"}, **kw)
        if r.status_code >= 400 and r.status_code != 422:
            r.raise_for_status()
        return r.json() if r.content else None

    def ensure_labels(self):
        for name, color in (("found", "c2b8a3"), ("approved", "2e7d32")):
            self._req("POST", "/labels", json={"name": name, "color": color})

    def open_issue(self, title, body):
        return self._req("POST", "/issues", json={"title": title, "body": body, "labels": ["found"]})

    def issues(self, label):
        return self._req("GET", "/issues", params={"labels": label, "state": "open", "per_page": 100}) or []

    def comment(self, number, body, close=False):
        self._req("POST", f"/issues/{number}/comments", json={"body": body})
        if close:
            self._req("PATCH", f"/issues/{number}", json={"state": "closed"})
