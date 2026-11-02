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
SPACING = 5.0  # windows with start AND end within this many seconds of a kept one are dropped
OPENER_WORDS = 15

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


def split_sentences(words: list[dict], gap: float = SENTENCE_GAP) -> list[list[dict]]:
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["w"][-1] in ".?!" or nxt is None or nxt["s"] - w["e"] > gap:
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
            if sub is None and dur >= min_dur and sent_text(sents[j])[-1] in "?!":
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
        if c["start"] <= t < c["end"]:
            return c["title"]
    return None


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
        gist = sent_text(sents[i]) if j == i else sent_text(sents[i]) + " … " + sent_text(sents[j])
        items.append({
            "id": 0,
            "start": round(start, 2),
            "end": round(end, 2),
            "dur_raw": round(end - start, 1),
            "dur_tight": round(tight, 1),
            "opener": " ".join(w["w"] for w in ws[:OPENER_WORDS]),
            "gist": gist,
            "signals": {
                "comment_hits": sum(1 for k in kws if k in low),
                "chapter": chapter_at(chapters, (start + end) / 2),
                "has_question": "?" in text,
                "pace": round((len(ws) / max(tight, 1.0)) / video_pace, 2),
            },
        })

    # Prefer strong signals and ~40s length, then enforce diversity and the cap.
    items.sort(key=lambda c: (c["signals"]["comment_hits"] + int(c["signals"]["has_question"]),
                              -abs(c["dur_tight"] - 40)), reverse=True)
    kept: list[dict] = []
    for c in items:
        if all(abs(c["start"] - k["start"]) >= SPACING or abs(c["end"] - k["end"]) >= SPACING for k in kept):
            kept.append(c)
        if len(kept) >= cfg["max_candidates"]:
            break
    kept.sort(key=lambda c: c["start"])
    for n, c in enumerate(kept, 1):
        c["id"] = n
    return kept


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    args = ap.parse_args()
    slug = resolve_slug(args.slug)
    wdir = WORKSPACE / slug
    if not (wdir / "words.json").exists():
        die("words.json missing; run transcribe.py first")
    words = load_json(wdir / "words.json")
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
