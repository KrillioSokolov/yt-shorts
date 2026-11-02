import candidates


def mk_words(sentences, start=0.0, word_dur=0.3, gap=0.1, sentence_gap=0.4):
    """Build word dicts from a list of sentence strings with regular timing."""
    words, t = [], start
    for sent in sentences:
        for token in sent.split():
            words.append({"w": token, "s": round(t, 3), "e": round(t + word_dur, 3)})
            t += word_dur + gap
        t += sentence_gap
    return words


def test_split_sentences_on_punctuation_and_gap():
    words = mk_words(["Hello there.", "How are you?", "Fine"])
    words.append({"w": "later", "s": words[-1]["e"] + 2.0, "e": words[-1]["e"] + 2.3})
    sents = candidates.split_sentences(words)
    assert [candidates.sent_text(s) for s in sents] == ["Hello there.", "How are you?", "Fine", "later"]


def test_build_windows_respects_duration_bounds():
    # 10 sentences x 5 words x 0.4s = 2s each + 0.4 gap => ~2.4s per sentence
    words = mk_words([f"w{i} w w w w." for i in range(30)])
    sents = candidates.split_sentences(words)
    wins = candidates.build_windows(sents, min_dur=20, max_dur=58)
    assert wins, "expected at least one window"
    for i, j in wins:
        dur = sents[j][-1]["e"] - sents[i][0]["s"]
        assert 20 <= dur <= 58


def test_build_windows_emits_question_subwindow():
    sents_text = [f"s{i} a b c d." for i in range(10)] + ["why is that?"] + [f"t{i} a b c d." for i in range(15)]
    words = mk_words(sents_text)
    sents = candidates.split_sentences(words)
    wins = candidates.build_windows(sents, min_dur=20, max_dur=58)
    q_idx = 10
    assert any(j == q_idx for _, j in wins)


def test_keywords_from_comments_filters_stopwords_and_short():
    kws = candidates.keywords_from_comments(
        ["Great video about python tutorials", "python tutorials rock", "the the the"])
    assert kws[:2] == ["python", "tutorials"]   # 2 hits each, alphabetical tiebreak
    assert "great" not in kws                   # stopword
    assert "about" not in kws                   # stopword
    assert "video" not in kws                   # stopword
    assert "the" not in kws and "rock" not in kws  # too short (<5 chars)


def test_chapter_at():
    chapters = [{"title": "Intro", "start": 0, "end": 10}, {"title": "Main", "start": 10, "end": 50}]
    assert candidates.chapter_at(chapters, 5) == "Intro"
    assert candidates.chapter_at(chapters, 10) == "Main"
    assert candidates.chapter_at(chapters, 99) is None


def test_make_candidates_shape_and_cap():
    words = mk_words([f"s{i} alpha beta gamma delta." for i in range(80)])
    meta = {"comments": ["alpha is key", "delta rocks"], "chapters": []}
    cfg = {"gap_threshold": 0.6, "gap_keep": 0.25, "max_candidates": 5}
    out = candidates.make_candidates(words, meta, cfg)
    assert 1 <= len(out) <= 5
    assert [c["id"] for c in out] == list(range(1, len(out) + 1))
    assert out == sorted(out, key=lambda c: c["start"])
    c = out[0]
    assert set(c) == {"id", "start", "end", "dur_raw", "dur_tight", "opener", "gist", "signals"}
    assert set(c["signals"]) == {"comment_hits", "chapter", "has_question", "pace"}
    assert c["signals"]["comment_hits"] >= 1
    assert c["dur_tight"] <= c["dur_raw"]
