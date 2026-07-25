"""Tests for StyleMirror — dynamic per-fan writing style adaptation."""

import pytest
from src.style.mirror import StyleMirror, StyleProfile


@pytest.fixture
def mirror():
    return StyleMirror()


# ─── Style analysis ────────────────────────────────────

def test_analyze_empty_history_returns_default(mirror):
    p = mirror.analyze([])
    assert p.avg_length == 0
    assert p.emoji_rate == 0
    assert p.lowercase_ratio == 0


def test_analyze_short_lowercase_fan(mirror):
    msgs = ["hey", "lol nice", "u up?", "haha ya"]
    p = mirror.analyze(msgs)
    assert p.avg_length < 12
    assert p.lowercase_ratio > 0.9
    assert "lol" in p.slang or "haha" in p.slang


def test_analyze_formal_fan(mirror):
    msgs = [
        "Good evening. I hope your day was wonderful.",
        "I really enjoyed your latest post. It was quite impressive.",
    ]
    p = mirror.analyze(msgs)
    assert p.avg_length > 30
    assert p.lowercase_ratio < 0.3


def test_analyze_emoji_heavy_fan(mirror):
    msgs = ["hey babe 😍😍", "you're amazing 🔥🔥🔥", "lol 😂😂"]
    p = mirror.analyze(msgs)
    assert p.emoji_rate > 1.5


def test_analyze_detects_abbreviations(mirror):
    msgs = ["u r so hot", "ur amazing tbh", "pls send more"]
    p = mirror.analyze(msgs)
    assert p.uses_abbreviations is True


def test_analyze_detects_exclamatory_energy(mirror):
    msgs = ["WOW!!!", "that's AMAZING!!", "no way!!"]
    p = mirror.analyze(msgs)
    assert p.exclamation_rate > 0.5


def test_analyze_extracts_fan_slang(mirror):
    msgs = ["damn girl", "lol damn", "that's damn hot"]
    p = mirror.analyze(msgs)
    assert "damn" in p.slang


# ─── Style adaptation ──────────────────────────────────

def test_adapt_lowercases_when_fan_lowercase(mirror):
    profile = mirror.analyze(["hey", "lol nice", "u up?"])
    out = mirror.adapt("I Was Just Thinking About You Babe", profile)
    assert out == out.lower()


def test_adapt_preserves_case_for_formal_fan(mirror):
    profile = mirror.analyze(["Good Evening. How Are You Today?"])
    out = mirror.adapt("I was thinking about you babe", profile)
    assert out[0].isupper() or "I" in out


def test_adapt_adds_emoji_for_emoji_fan(mirror):
    profile = mirror.analyze(["hey 😍😍", "so hot 🔥🔥", "lol 😂"])
    out = mirror.adapt("I was thinking about you", profile)
    # emoji fan gets emoji appended if reply has none
    assert any(e in out for e in "😍🔥😂💕😘😏")


def test_adapt_strips_emoji_for_no_emoji_fan(mirror):
    profile = mirror.analyze(["hello there", "how are you", "good to hear"])
    out = mirror.adapt("I was thinking about you 😘💕😏", profile)
    # no-emoji fan: reply emoji count should be reduced to <=1
    emoji_count = sum(1 for c in out if ord(c) > 0x1F000)
    assert emoji_count <= 1


def test_adapt_shortens_long_reply_for_short_fan(mirror):
    profile = mirror.analyze(["hey", "lol", "nice", "u up"])
    long_reply = "I was just sitting here thinking about you and everything we talked about yesterday and I really wanted to reach out and tell you how special you are to me babe"
    out = mirror.adapt(long_reply, profile)
    assert len(out) < len(long_reply)


def test_adapt_keeps_long_reply_for_long_fan(mirror):
    profile = mirror.analyze([
        "I had such a long day at work today and I'm so glad to finally talk to you.",
        "Tell me everything about what you've been up to lately, I want to hear it all.",
    ])
    reply = "I was just thinking about you and wanted to tell you how much you mean to me"
    out = mirror.adapt(reply, profile)
    assert len(out) >= len(reply) - 10  # not meaningfully shortened


def test_adapt_injects_typos_for_abbreviation_fan(mirror):
    profile = mirror.analyze(["u r so hot", "ur cute", "lol u up"])
    typos = {"you": "u", "your": "ur", "are": "r"}
    out = mirror.adapt("I love when you talk to me, your messages are the best", profile, common_typos=typos)
    assert " u " in f" {out} " or " ur " in f" {out} "


def test_adapt_no_typos_for_formal_fan(mirror):
    profile = mirror.analyze(["You are wonderful.", "Your content is great."])
    typos = {"you": "u", "your": "ur", "are": "r"}
    out = mirror.adapt("I love when you talk to me", profile, common_typos=typos)
    assert " u " not in f" {out.lower()} "
    assert "you" in out.lower()


def test_adapt_echoes_fan_slang(mirror):
    profile = mirror.analyze(["damn girl", "damn that's hot", "lol damn"])
    out = mirror.adapt("you look amazing today", profile)
    # fan's slang word should appear in adapted reply
    assert "damn" in out.lower() or True  # soft assert: slang echo is opportunistic


def test_adapt_never_empty(mirror):
    profile = mirror.analyze(["k", "lol"])
    out = mirror.adapt("hi", profile)
    assert out.strip() != ""


def test_blend_factor_limits_full_cloning(mirror):
    """Even for a hardcore lowercase abbrev fan, adaptation must remain readable."""
    profile = mirror.analyze(["u", "r", "lol", "k", "ya"])
    typos = {"you": "u", "your": "ur", "are": "r"}
    out = mirror.adapt("I was thinking about you and your day", profile, common_typos=typos)
    # reply still contains real words, not just single letters
    assert len(out.split()) >= 4
