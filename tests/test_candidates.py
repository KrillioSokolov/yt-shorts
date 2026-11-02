import json

import pytest

import candidates
import common


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
    assert set(c) == {"id", "start", "end", "dur_raw", "dur_tight", "opener", "gist", "signals", "score"}
    assert isinstance(c["score"], float)
    assert set(c["signals"]) == {"comment_hits", "chapter", "has_question", "pace"}
    assert c["signals"]["comment_hits"] >= 1
    assert c["dur_tight"] <= c["dur_raw"]


def test_iou():
    assert candidates.iou((0, 10), (20, 30)) == 0.0
    assert candidates.iou((0, 10), (10, 20)) == 0.0
    assert candidates.iou((3, 9), (3, 9)) == 1.0
    assert candidates.iou((0, 10), (5, 15)) == pytest.approx(1 / 3)


def test_selection_spreads_coverage():
    # ~5 minutes of 5-word sentences (~2.4 s each); comment keywords appear only in the first ~60 s.
    sents = [f"s{i} alpha delta gamma beta." for i in range(25)] + [f"t{i} one two three four." for i in range(100)]
    words = mk_words(sents)
    assert words[-1]["e"] > 290
    meta = {"comments": ["alpha is key", "delta rocks"], "chapters": []}
    cfg = {"gap_threshold": 0.6, "gap_keep": 0.25, "max_candidates": 25}
    out = candidates.make_candidates(words, meta, cfg)
    assert 1 <= len(out) <= 25
    for a in range(len(out)):
        for b in range(a + 1, len(out)):
            spans = (out[a]["start"], out[a]["end"]), (out[b]["start"], out[b]["end"])
            assert candidates.iou(*spans) <= candidates.MAX_IOU + 1e-9
    assert any(c["start"] > 150 for c in out)
    assert [c["id"] for c in out] == list(range(1, len(out) + 1))
    assert out == sorted(out, key=lambda c: c["start"])


def test_question_subwindow_survives_selection():
    # Sentence 10 (a question) ends ~26 s after t=0; the longest run from t=0 is ~57 s.
    sents = [f"s{i} a b c d." for i in range(10)] + ["why is that so?"] + [f"t{i} a b c d." for i in range(15)]
    words = mk_words(sents)
    meta = {"comments": [], "chapters": []}
    cfg = {"gap_threshold": 0.6, "gap_keep": 0.25, "max_candidates": 25}
    out = candidates.make_candidates(words, meta, cfg)
    from_zero = [c for c in out if c["start"] == 0.0]
    ends = sorted(c["end"] for c in from_zero)
    assert len(ends) == 2, from_zero
    assert 20 <= ends[0] <= 30          # question sub-window
    assert 50 <= ends[1] <= 58          # longest window from the same start


def test_split_sentences_handles_trailing_quote_and_empty_token():
    words = [{"w": "He", "s": 0.0, "e": 0.2}, {"w": 'done."', "s": 0.3, "e": 0.5},
             {"w": "Next", "s": 0.6, "e": 0.8}, {"w": "", "s": 0.9, "e": 0.9},
             {"w": "word", "s": 1.0, "e": 1.2}]
    sents = candidates.split_sentences(words)
    assert [candidates.sent_text(s) for s in sents] == ['He done."', "Next  word"]
    assert candidates.split_sentences([{"w": "", "s": 0.0, "e": 0.1}]) == [[{"w": "", "s": 0.0, "e": 0.1}]]


def test_comment_hits_token_match_not_substring():
    kws = candidates.keywords_from_comments(["training matters"])
    assert "training" in kws
    assert candidates.comment_hits(kws, "you have to train every day") == 0
    assert candidates.comment_hits(kws, "the training is the point") == 1


def test_main_dies_on_empty_words(tmp_path, monkeypatch, capsys):
    slug = "empty-video"
    d = tmp_path / slug
    d.mkdir()
    (d / "words.json").write_text("[]", encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"title": "t", "comments": [], "chapters": []}), encoding="utf-8")
    monkeypatch.setattr(common, "WORKSPACE", tmp_path)
    monkeypatch.setattr(candidates, "WORKSPACE", tmp_path)
    monkeypatch.setattr("sys.argv", ["candidates.py", slug])
    with pytest.raises(SystemExit) as exc:
        candidates.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("ERROR:")
    assert "empty" in out
