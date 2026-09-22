"""Everything the bot decides: reading votes and submissions, weighting pairs, reading the mood.

Pure functions only (no network), so simulate.py can exercise them offline.
"""
import itertools
import re
from collections import Counter, defaultdict

# ---------- reading replies ----------

HOLDS = {"=", "holds"}
BREAKS = {"≠", "!=", "=/=", "breaks"}
_TOKEN = re.compile(r"=/=|≠|!=|=|[a-z]+")


def parse_vote(text):
    """A vote is the first token of a reply: = / holds, or ≠ / != / breaks."""
    text = re.sub(r"^(@\S+\s*)+", "", (text or "").strip().lower())  # skip leading @mentions
    m = _TOKEN.match(text)
    if not m:
        return None
    tok = m.group(0)
    return "holds" if tok in HOLDS else "breaks" if tok in BREAKS else None


def is_submission(text):
    return bool(re.search(r"#found\b", text or "", re.I))


def parse_submission(text, links):
    """Best-effort parse of: #found “quote text” — Speaker, Work (Year) [link]."""
    body = re.sub(r"#found\b", "", text, flags=re.I).strip()
    body = re.sub(r"https?://\S+", "", body).strip()
    m = re.search(r"[“\"](.+?)[”\"]\s*[—–-]+\s*(.+)", body, re.S)
    quote, attr = (m.group(1).strip(), m.group(2).strip()) if m else (body, "")
    year = None
    bce = re.search(r"(\d{1,4})\s*BCE", attr)
    yrs = re.findall(r"\b(\d{3,4})\b", attr)
    if bce:
        year = -int(bce.group(1))
    elif yrs:
        year = int(yrs[-1])
    speaker = re.split(r"[,(]", attr)[0].strip() if attr else ""
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", speaker.lower()).strip("-")[:40] or "new-quote",
        "year": year,
        "text": quote,
        "attribution": attr,
        "short": f"{speaker} ({abs(year)}{' BCE' if year and year < 0 else ''})" if speaker and year else speaker,
        "url": links[0] if links else "",
        "strands": [],
    }

# ---------- pairing ----------

MODES = ("random", "cross-era", "same-strand", "cross-strand", "curated")


def eligible_pairs(quotes, mode, cfg):
    cut = cfg["era_cutoff"]
    blocked = {frozenset(p) for p in cfg.get("blocklist", [])}
    if mode == "curated":
        raw = [tuple(p) for p in cfg["curated"]]
    else:
        raw = []
        for a, b in itertools.combinations(sorted(quotes), 2):
            qa, qb = quotes[a], quotes[b]
            cross = (qa["year"] < cut) != (qb["year"] < cut)
            shared = bool(set(qa.get("strands", [])) & set(qb.get("strands", [])))
            ok = {"random": True, "cross-era": cross,
                  "same-strand": cross and shared, "cross-strand": cross and not shared}[mode]
            if ok:
                raw.append((a, b))
    pairs = [p for p in raw if p[0] in quotes and p[1] in quotes and frozenset(p) not in blocked]
    return [tuple(sorted(p, key=lambda i: (quotes[i]["year"], i))) for p in pairs]


def contest(h, b, k):
    """0 when everyone agrees or no one voted; approaches 1 as votes split evenly and pile up."""
    n = h + b
    if n == 0:
        return 0.0
    return (1 - abs(h - b) / n) * (n / (n + k))


def tallies(log):
    """Vote counts per pair and per quote across every post so far."""
    per_pair, per_quote = defaultdict(Counter), defaultdict(Counter)
    for p in log:
        c = Counter(p.get("votes", {}).values())
        per_pair[frozenset(p["pair"])].update(c)
        for q in p["pair"]:
            per_quote[q].update(c)
    return per_pair, per_quote


def pick(quotes, log, mode, cfg, rng, today):
    w = cfg["weights"]
    pairs = eligible_pairs(quotes, mode, cfg)
    if not pairs:
        pairs = eligible_pairs(quotes, "random", cfg)
    recent = {frozenset(p["pair"]) for p in log[-w["no_repeat"]:]}
    cands = [p for p in pairs if frozenset(p) not in recent] or pairs
    per_pair, per_quote = tallies(log)
    posted = {frozenset(p["pair"]) for p in log}
    ever = {q for p in log for q in p["pair"]}

    def weight(p):
        cq = sum(contest(per_quote[q]["holds"], per_quote[q]["breaks"], w["k"]) for q in p)
        pc = per_pair[frozenset(p)]
        cp = contest(pc["holds"], pc["breaks"], w["k"])
        unseen = frozenset(p) not in posted
        fresh = any(quotes[q].get("found_by") and q not in ever for q in p)
        return (w["floor"]
                + (1 + w["unseen"] * unseen + w["fresh"] * fresh)
                * (1 + w["quote_contest"] * cq + w["pair_contest"] * cp))

    weights = [weight(p) for p in cands]
    return rng.choices(cands, weights=weights, k=1)[0]

# ---------- mood ----------

def capped_votes(posts, cap):
    """Each account's votes count at most `cap` times per window, so a few accounts can't steer the mood."""
    seen, out = Counter(), Counter()
    for p in posts:
        for voter, v in p.get("votes", {}).items():
            if seen[voter] < cap:
                seen[voter] += 1
                out[v] += 1
    return out


def read_mood(posts, cfg):
    m = cfg["mood"]
    votes = capped_votes(posts, m["max_votes_per_account"])
    h, b = votes["holds"], votes["breaks"]
    n = h + b
    eng = sum(p.get("likes", 0) + p.get("reposts", 0) + p.get("replies", 0) + p.get("quotes", 0) for p in posts)
    per_post = eng / max(len(posts), 1)
    if n < m["min_votes"]:
        mood = "quiet" if per_post < m["quiet_engagement"] else "unclear"
    elif b / n >= m["lopsided"]:
        mood = "objecting"
    elif h / n >= m["lopsided"]:
        mood = "agreeing"
    else:
        mood = "contested"
    return mood, {"holds": h, "breaks": b, "engagement": eng, "per_post": per_post}


def most_contested(posts):
    best, score = None, 0
    for p in posts:
        c = Counter(p.get("votes", {}).values())
        s = contest(c["holds"], c["breaks"], 1)
        if c["holds"] + c["breaks"] >= 2 and s > score:
            best, score = p, s
    return best
