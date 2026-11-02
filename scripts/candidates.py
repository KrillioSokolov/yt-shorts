"""Pre-chunk the transcript into short-form candidate windows -> candidates.json

Usage:
    python scripts/candidates.py [slug]
Claude reads candidates.json (compact) and scores it; nothing here needs tokens.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, compute_keep_ranges, die, load_config, load_json, ranges_duration, resolve_slug, save_json  # noqa: E402

MIN_DUR = 20.0
MAX_DUR = 58.0
SENTENCE_GAP = 0.7
MAX_IOU = 0.6  # a window overlapping any kept window more than this (intersection/union) is dropped
OPENER_WORDS = 15
GIST_WORDS = 25
SENT_END = ".?!…"
TRAILING_CLOSERS = "\"'”’)]»"

STOPWORDS = {
    "about", "above", "after", "again", "against", "really", "would", "could", "should", "there",
    "their", "these", "those", "which", "while", "where", "because", "being", "before", "between",
    "under", "until", "video", "videos", "thanks", "thank", "please", "watch", "watching", "channel",
    "subscribe", "great", "awesome", "amazing", "love", "loved", "think", "thing", "things", "something",
    "every", "everyone", "people", "always", "never", "still", "other", "another", "doesn", "didn",
    "wasn", "aren", "isn", "can't", "don't", "doesn't", "didn't", "that's", "there's", "you're", "it's",
    "going", "getting", "making", "makes", "first", "pretty", "actually", "literally", "basically",
}


def sent_text(sent: list[dict]) -> str:
    return " ".join(w["w"] for w in sent)


def last_char(text: str) -> str:
    """Final character ignoring trailing whitespace, quotes and brackets ('' if none)."""
    return text.rstrip().rstrip(TRAILING_CLOSERS)[-1:]


def split_sentences(words: list[dict], gap: float = SENTENCE_GAP) -> list[list[dict]]:
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        last = w["w"].rstrip(TRAILING_CLOSERS)[-1:]
        if (last and last in SENT_END) or nxt is None or nxt["s"] - w["e"] > gap:
            sents.append(cur)
            cur = []
    return sents


def build_windows(sents: list[list[dict]], min_dur: float = MIN_DUR, max_dur: float = MAX_DUR) -> list[tuple[int, int]]:
    """Return (i, j) inclusive sentence-index windows whose raw duration is within bounds.

    For each start i: the longest run that fits, plus the first run that ends on a ? or ! sentence.
    """
    wins: set[tuple[int, int]] = set()
    for i in range(len(sents)):
        start = sents[i][0]["s"]
        j, sub = i, None
        while j < len(sents) and sents[j][-1]["e"] - start <= max_dur:
            dur = sents[j][-1]["e"] - start
            if sub is None and dur >= min_dur and last_char(sent_text(sents[j])) in ("?", "!"):
                sub = j
            j += 1
        j -= 1
        if j >= i and sents[j][-1]["e"] - start >= min_dur:
            wins.add((i, j))
            if sub is not None and sub != j:
                wins.add((i, sub))
    return sorted(wins)


def keywords_from_comments(comments: list[str], top: int = 40) -> list[str]:
    freq: dict[str, int] = {}
    for c in comments:
        for token in set(re.findall(r"[a-z][a-z']{4,}", c.lower())):
            if token not in STOPWORDS:
                freq[token] = freq.get(token, 0) + 1
    return [k for k, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]


def chapter_at(chapters: list[dict], t: float) -> str | None:
    for c in chapters:
        start, end = c.get("start"), c.get("end")
        if start is None or end is None:
            continue
        if start <= t < end:
            return c.get("title")
    return None


def iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Intersection over union of two [start, end] intervals."""
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def cap_words(text: str, n: int = GIST_WORDS) -> str:
    toks = text.split()
    return text if len(toks) <= n else " ".join(toks[:n]) + "…"


def comment_hits(kws: list[str], low_text: str) -> int:
    """Count comment keywords present as whole tokens in the (lower-cased) window text."""
    tokens = set(re.findall(r"[a-z][a-z']+", low_text))
    return sum(1 for k in kws if k in tokens)


def score(c: dict) -> float:
    sig = c["signals"]
    dur = c["dur_tight"]
    hits_per_30s = sig["comment_hits"] / max(dur, 1.0) * 30
    return hits_per_30s + (1.0 if sig["has_question"] else 0.0) - abs(dur - 40) / 60


def select_diverse(items: list[dict], max_n: int, max_iou: float = MAX_IOU) -> list[dict]:
    """Greedy: best score first, keep a window only if its IoU with every kept one is <= max_iou."""
    if max_n <= 0:
        return []
    kept: list[dict] = []
    for c in sorted(items, key=lambda c: (-c["score"], c["start"])):
        span = (c["start"], c["end"])
        if all(iou(span, (k["start"], k["end"])) <= max_iou for k in kept):
            kept.append(c)
            if len(kept) >= max_n:
                break
    kept.sort(key=lambda c: c["start"])
    for n, c in enumerate(kept, 1):
        c["id"] = n
    return kept


def make_candidates(words: list[dict], meta: dict, cfg: dict) -> list[dict]:
    sents = split_sentences(words)
    kws = keywords_from_comments(meta.get("comments") or [])
    chapters = meta.get("chapters") or []
    total = words[-1]["e"] - words[0]["s"]
    video_pace = len(words) / total if total > 0 else 1.0

    items = []
    for i, j in build_windows(sents):
        ws = [w for s in sents[i:j + 1] for w in s]
        start, end = ws[0]["s"], ws[-1]["e"]
        text = " ".join(w["w"] for w in ws)
        low = text.lower()
        tight = ranges_duration(compute_keep_ranges(ws, start, end, cfg["gap_threshold"], cfg["gap_keep"]))
        first = cap_words(sent_text(sents[i]))
        gist = first if j == i else first + " … " + cap_words(sent_text(sents[j]))
        item = {
            "id": 0,
            "start": round(start, 2),
            "end": round(end, 2),
            "dur_raw": round(end - start, 1),
            "dur_tight": round(tight, 1),
            "opener": " ".join(w["w"] for w in ws[:OPENER_WORDS]),
            "gist": gist,
            "signals": {
                "comment_hits": comment_hits(kws, low),
                "chapter": chapter_at(chapters, (start + end) / 2),
                "has_question": "?" in text,
                "pace": round((len(ws) / max(end - start, 1.0)) / video_pace, 2),
            },
        }
        # Weak prior for Claude: keyword density + question bonus, nudged toward ~40s.
        item["score"] = round(score(item), 2)
        items.append(item)

    return select_diverse(items, cfg["max_candidates"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    args = ap.parse_args()
    slug = resolve_slug(args.slug)
    wdir = WORKSPACE / slug
    if not (wdir / "words.json").exists():
        die("words.json missing; run transcribe.py first")
    words = load_json(wdir / "words.json")
    if not words:
        die("words.json is empty; no speech to clip")
    meta = load_json(wdir / "meta.json")
    cfg = load_config()
    cands = make_candidates(words, meta, cfg)
    if not cands:
        die("no 20-58s candidate windows found (video too short or no sentence boundaries)")
    save_json(wdir / "candidates.json", {"slug": slug, "video_title": meta["title"],
                                         "video_duration": meta.get("duration"), "candidates": cands})
    print(f"candidates: {len(cands)}")
    print(f"file:       {wdir / 'candidates.json'}")


if __name__ == "__main__":
    main()
