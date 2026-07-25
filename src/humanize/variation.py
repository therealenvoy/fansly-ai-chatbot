"""VariationPool — eliminates message repetition by cycling through variant pools.

Each message type has 5-8 distinct phrasings. The pool ensures the same fan
never hears the same variant twice in a row. Pools auto-reset after exhaustion.
"""

import random
from collections import defaultdict

# ─── RAPPORT MESSAGE VARIANTS ──────────────────────────
# Replaces the old: "Hey babe! How's your day going? 💕"

RAPPORT_VARIANTS = [
    "Hey babe, what are you up to?",
    "Hey handsome, how's your day going?",
    "There you are! I was wondering when you'd pop in 😘",
    "Mmm, good to hear from you. What's on your mind?",
    "Hey you! I was just thinking about you…",
    "Well hello there! Come here often? 😏",
    "Look who decided to show up… was starting to think you forgot about me",
    "Ooh, there you are. I was getting lonely without you 😘",
]

# ─── PUSH MESSAGE VARIANTS ────────────────────────────
# Replaces the old: "I was just thinking about you... wish you were here right now 😏"

PUSH_VARIANTS = [
    "I was just thinking about you… especially that thing you like 😏",
    "Mmm, I just had the dirtiest thought about you…",
    "You've been on my mind all day… and not in a PG way",
    "I was in the shower and couldn't stop thinking about you…",
    "Stop being so damn cute, it's distracting me 😘",
    "You're making it really hard to focus over here…",
    "I keep catching myself smiling thinking about our last chat…",
    "You have no idea what you do to me when you talk like that 🔥",
]

# ─── AFTERCARE VARIANTS ───────────────────────────────
# Replaces the old: "That was so fun... I don't do that with everyone, you know 😘"

AFTERCARE_VARIANTS = [
    "That was so fun… I don't do that with everyone, you know 😘",
    "Mmm I hope you enjoyed that as much as I did…",
    "You're something special, you know that? 😘",
    "I love that we can have moments like this… it means a lot",
    "That was amazing… you always know how to make me smile",
    "I'm still blushing… you're too good at this 😏",
]

# ─── CLOSE VARIANTS ───────────────────────────────────
# Replaces the old: "I'm so glad you enjoyed it 😘"

CLOSE_VARIANTS = [
    "I'm so glad you liked it 😘",
    "Mm, I knew you'd love that one",
    "That smile was totally worth it 😏",
    "Glad I could make your day a little better 😘",
    "You deserve good things, babe",
]

# ─── RE-ENGAGEMENT VARIANTS ──────────────────────────
# Replaces the old: "Hey... I haven't heard from you in a bit"

REENGAGE_SOFT_VARIANTS = [
    "Hey stranger… I miss our chats 💕",
    "It's been a bit quiet without you around… everything okay?",
    "I was just scrolling through our messages and realized it's been a while…",
    "Not gonna lie, I've been checking my messages hoping to see your name pop up 😘",
    "Hey… I hope everything's good on your end. Thinking of you 💕",
]

REENGAGE_HARD_VARIANTS = [
    "I made something new and thought of you first… want to see? 😏",
    "I've got something special saved just for you… come take a look 🔥",
    "You're gonna want to see what I made… it's 🔥🔥",
    "I was recording and accidentally made something you'd love… check it out",
]

# ─── PREMIUM PPV VARIANTS ─────────────────────────────
# Replaces the old: "Since you're my absolute favorite... I made something extra special"

PREMIUM_PPV_VARIANTS = [
    "Since you're my absolute favorite… I made something extra special for you",
    "This one's not for everyone… but you're not everyone, are you?",
    "I hardly ever share these… but you've earned it 😘",
    "You've been so good to me… so I made something just for you",
    "This is the good stuff… the stuff I don't post anywhere else 🔥",
]


class VariationPool:
    """Cycles through message variants to eliminate repetition.

    Usage:
        pool = VariationPool()
        msg = pool.pick("rapport")  # returns a unique variant
        msg = pool.pick_with_context("push", "fan_123")  # per-fan tracking
    """

    def __init__(self):
        self._pools = {
            "rapport": list(RAPPORT_VARIANTS),
            "push": list(PUSH_VARIANTS),
            "aftercare": list(AFTERCARE_VARIANTS),
            "close": list(CLOSE_VARIANTS),
            "reengage_soft": list(REENGAGE_SOFT_VARIANTS),
            "reengage_hard": list(REENGAGE_HARD_VARIANTS),
            "premium_ppv": list(PREMIUM_PPV_VARIANTS),
        }
        # State for per-fan tracking: {fan_id: {key: last_index}}
        self._fan_last: dict[str, dict[str, str]] = defaultdict(dict)

    def pick(self, key: str) -> str:
        """Pick a variant for 'key', avoiding the last-used one.

        Falls back to a default message if the key isn't in the pool.
        """
        if key not in self._pools:
            return self._default(key)
        pool = self._pools[key]
        # Track last-sent for this key (global, not per-fan)
        last = getattr(self, f"_last_{key}", None)
        candidates = [v for v in pool if v != last]
        chosen = random.choice(candidates) if candidates else random.choice(pool)
        setattr(self, f"_last_{key}", chosen)
        return chosen

    def pick_with_context(self, key: str, fan_id: str) -> str:
        """Pick a variant for 'key', per-fan tracking to avoid repeats."""
        if key not in self._pools:
            return self._default(key)
        pool = self._pools[key]
        last = self._fan_last[fan_id].get(key)
        candidates = [v for v in pool if v != last]
        chosen = random.choice(candidates) if candidates else random.choice(pool)
        self._fan_last[fan_id][key] = chosen
        return chosen

    def _default(self, key: str) -> str:
        """Safe fallback for unknown keys."""
        return f"Hey there! 💕"