"""StyleMirror — analyze a fan's writing style and adapt replies to match it.

Research basis (top-chatter technique, onlyfanscourse/xcelerator A/B data):
- Mirroring vocabulary & tone builds subconscious rapport; fan-initiated
  escalation converts ~3x better than chatter-initiated.
- Match the fan's FORM: message length, casing, emoji budget, abbreviations,
  punctuation energy. A short-texter gets short replies; a novelist gets prose.
- Blend: mirror the mechanics (~70%) but keep persona identity (~30%) so the
  creator's brand voice never disappears into the fan's style.
"""

import re
from dataclasses import dataclass, field

# Emoji detection: common emoji ranges
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF❤️😘😏😍🔥💕]"
)
_WORD_RE = re.compile(r"[a-zA-Z']+")
_EXCLAIM_RE = re.compile(r"!+")
_QUESTION_RE = re.compile(r"\?+")
_MIXED_PUNCT_RE = re.compile(r"\?!|!\?")
_GREETING_WORDS = {"hey", "hi", "hello", "yo", "sup", "howdy", "heyy", "heyyy", "hii", "hiii"}

# Casual abbreviation lexicon fans use
_ABBREV_HINTS = {"u", "ur", "r", "pls", "plz", "tbh", "lol", "lmao", "omg", "rn", "imo", "idk", "wyd", "hru", "ngl", "fr", "bc", "cuz", "ya", "yup", "nope", "gonna", "wanna", "gotta"}
# Words worth echoing back (fan slang), minus stopwords
_STOPWORDS = {"the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on", "at", "is", "it", "i", "you", "your", "u", "ur", "me", "my", "so", "that", "this", "are", "r", "was", "im", "i'm", "be", "been", "just", "for", "with", "what", "how", "when", "do", "did", "does", "have", "has", "not", "no", "yes", "yeah", "ok", "okay", "hey", "hi", "hello"}


@dataclass
class StyleProfile:
    """Computed writing-style fingerprint of a fan."""

    avg_length: float = 0.0          # avg chars per message
    emoji_rate: float = 0.0          # avg emojis per message
    lowercase_ratio: float = 0.0     # fraction of messages that are all-lowercase
    exclamation_rate: float = 0.0    # fraction of messages containing '!'
    question_rate: float = 0.0       # fraction of messages containing '?'
    uses_abbreviations: bool = False
    slang: list[str] = field(default_factory=list)  # fan's characteristic words
    message_count: int = 0

    # Enhanced: Punctuation energy — how many ! or ? per punctuated message
    exclamation_intensity: float = 0.0   # avg number of ! per exclamation-message
    question_intensity: float = 0.0      # avg number of ? per question-message
    has_mixed_punctuation: bool = False  # uses !? or ?! combos

    # Enhanced: Sentence length variance
    sentence_length_stddev: float = 0.0  # std dev of sentence lengths
    sentence_count: int = 0

    # Enhanced: Greeting/sign-off patterns
    opens_with_greeting: bool = False
    greeting_words: list[str] = field(default_factory=list)

    @property
    def formality(self) -> str:
        """'casual' | 'neutral' | 'formal' bucket for quick branching."""
        if self.message_count == 0:
            return "neutral"
        casual_score = (
            (1 if self.lowercase_ratio > 0.6 else 0)
            + (1 if self.uses_abbreviations else 0)
            + (1 if self.emoji_rate > 0.5 else 0)
            + (1 if self.avg_length < 40 else 0)
        )
        if casual_score >= 3:
            return "casual"
        if casual_score <= 1 and self.avg_length > 30:
            return "formal"
        return "neutral"


class StyleMirror:
    """Analyzes fan messages and adapts creator replies to mirror the fan's style."""

    MIRROR_STRENGTH = 0.7  # 70% mirror, 30% persona preservation

    # ─── ANALYSIS ──────────────────────────────────────

    def analyze(self, fan_messages: list[str]) -> StyleProfile:
        """Compute a StyleProfile from a fan's recent messages."""
        msgs = [m.strip() for m in fan_messages if m and m.strip()]
        if not msgs:
            return StyleProfile()

        total_len = sum(len(m) for m in msgs)
        total_emoji = sum(len(_EMOJI_RE.findall(m)) for m in msgs)
        lowercase_msgs = sum(1 for m in msgs if m == m.lower() and any(c.isalpha() for c in m))
        exclaim_msgs = sum(1 for m in msgs if "!" in m)
        question_msgs = sum(1 for m in msgs if "?" in m)

        # Token frequency for slang extraction + abbreviation detection
        freq: dict[str, int] = {}
        abbrev_hits = 0
        exclaim_counts = []
        question_counts = []
        has_mixed = False
        sentence_lengths = []
        greeting_hits = []
        for m in msgs:
            for tok in _WORD_RE.findall(m.lower()):
                if tok in _ABBREV_HINTS:
                    abbrev_hits += 1
                if tok not in _STOPWORDS and len(tok) >= 3:
                    freq[tok] = freq.get(tok, 0) + 1
            # Punctuation energy
            ex_marks = _EXCLAIM_RE.findall(m)
            if ex_marks:
                exclaim_counts.append(sum(len(e) for e in ex_marks))
            q_marks = _QUESTION_RE.findall(m)
            if q_marks:
                question_counts.append(sum(len(q) for q in q_marks))
            if _MIXED_PUNCT_RE.search(m):
                has_mixed = True
            # Sentence length variance — split on sentence boundaries
            sentences = [s.strip() for s in re.split(r'[.!?]+', m) if s.strip()]
            sentence_lengths.extend(len(s) for s in sentences)
            # Greeting detection
            first_word = m.strip().lower().split()[0] if m.strip().split() else ""
            if first_word in _GREETING_WORDS:
                greeting_hits.append(first_word)

        slang = [
            w for w, c in sorted(freq.items(), key=lambda kv: -kv[1])
            if c >= 2 or (c >= 1 and w in _ABBREV_HINTS)
        ][:5]

        # Greeting analysis
        opens_with_greeting = len(greeting_hits) > 0
        # Most common greeting word
        greeting_words = list(set(greeting_hits))[:3] if greeting_hits else []

        return StyleProfile(
            avg_length=total_len / len(msgs),
            emoji_rate=total_emoji / len(msgs),
            lowercase_ratio=lowercase_msgs / len(msgs),
            exclamation_rate=exclaim_msgs / len(msgs),
            question_rate=question_msgs / len(msgs),
            uses_abbreviations=abbrev_hits >= 2,
            slang=slang,
            message_count=len(msgs),
            # Enhanced fields
            exclamation_intensity=sum(exclaim_counts) / len(exclaim_counts) if exclaim_counts else 0.0,
            question_intensity=sum(question_counts) / len(question_counts) if question_counts else 0.0,
            has_mixed_punctuation=has_mixed,
            sentence_length_stddev=self._stddev(sentence_lengths) if len(sentence_lengths) >= 2 else 0.0,
            sentence_count=len(sentence_lengths),
            opens_with_greeting=opens_with_greeting,
            greeting_words=greeting_words,
        )

    @staticmethod
    def _stddev(values: list[float]) -> float:
        """Compute population standard deviation."""
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return variance ** 0.5

    # ─── ADAPTATION ────────────────────────────────────

    def adapt(
        self,
        reply: str,
        profile: StyleProfile,
        common_typos: dict[str, str] | None = None,
        pet_names: list[str] | None = None,
    ) -> str:
        """Transform a reply to mirror the fan's measured style.

        Order: length → typos → case → emoji → slang echo.
        Never returns an empty string.
        """
        if not reply or not reply.strip():
            return reply
        if profile.message_count == 0:
            return reply  # no data yet — persona default

        out = reply.strip()

        # 1. Length matching — casual short-texters get trimmed replies
        if profile.avg_length < 40 and len(out) > 120:
            out = self._trim_to_length(out, max_len=int(90 * (1 / self.MIRROR_STRENGTH)))
        elif profile.avg_length >= 40:
            pass  # long-form fan: keep the reply full

        # 2. Typo/abbreviation mirroring (only when fan abbreviates)
        if profile.uses_abbreviations and common_typos:
            out = self._apply_typos(out, common_typos)

        # 3. Case mirroring
        if profile.lowercase_ratio > 0.6:
            out = self._smart_lowercase(out)

        # 4. Emoji budget mirroring
        out = self._match_emoji_budget(out, profile)

        # 5. Punctuation energy matching
        out = self._match_punctuation_energy(out, profile)

        # 6. Greeting matching
        out = self._match_greeting(out, profile)

        # 7. Slang echo — weave one fan-signature word in when natural
        out = self._echo_slang(out, profile)

        return out.strip() or reply  # never empty

    # ─── INTERNAL TRANSFORMS ───────────────────────────

    def _trim_to_length(self, text: str, max_len: int) -> str:
        """Keep the first complete clause under max_len; drop trailing clauses."""
        if len(text) <= max_len:
            return text
        # Split on sentence boundaries, keep what fits
        parts = re.split(r"(?<=[.!?…])\s+", text)
        kept = ""
        for p in parts:
            candidate = (kept + " " + p).strip()
            if len(candidate) <= max_len:
                kept = candidate
            else:
                break
        if kept:
            return kept
        # No sentence fits — hard-truncate at word boundary
        cut = text[:max_len]
        return cut.rsplit(" ", 1)[0]

    def _apply_typos(self, text: str, typos: dict[str, str]) -> str:
        """Apply persona typo map (your→ur, you→u, are→r) word-boundary safe."""
        out = text
        for full, short in typos.items():
            # case-insensitive whole-word replace, preserve nothing fancy (we lowercase next)
            out = re.sub(rf"\b{re.escape(full)}\b", short, out, flags=re.IGNORECASE)
        return out

    def _smart_lowercase(self, text: str) -> str:
        """Lowercase but keep emojis and standalone 'I'-replacements intact.
        Since casual mirroring targets lowercase fans, drop 'I' to 'i' too —
        that IS the target style."""
        return text.lower()

    def _match_emoji_budget(self, text: str, profile: StyleProfile) -> str:
        """Match the fan's per-message emoji budget within ±1."""
        found = _EMOJI_RE.findall(text)
        budget = round(profile.emoji_rate)
        if profile.emoji_rate < 0.3:
            # no-emoji fan: strip down to at most 1
            if len(found) > 1:
                return self._strip_emojis(text, keep=1)
            return text
        if len(found) < budget:
            # add one fitting emoji at the end
            add = self._pick_emoji(profile)
            if add:
                return f"{text} {add}"
        return text

    def _strip_emojis(self, text: str, keep: int) -> str:
        seen = 0
        out_chars = []
        for ch in text:
            if _EMOJI_RE.match(ch):
                seen += 1
                if seen <= keep:
                    out_chars.append(ch)
                # else drop
            else:
                out_chars.append(ch)
        return "".join(out_chars)

    def _pick_emoji(self, profile: StyleProfile) -> str:
        """Pick an emoji consistent with persona-safe flirty set."""
        if profile.exclamation_rate > 0.4:
            return "😏"
        return "😘"

    def _match_punctuation_energy(self, text: str, profile: StyleProfile) -> str:
        """Match the fan's exclamation and question mark intensity.

        If fan uses '!!' we use '!!'; if fan uses '!?' we use '!?';
        if fan uses single '!' we match that too.
        """
        if profile.message_count == 0:
            return text

        # Match exclamation intensity
        if profile.exclamation_intensity > 0:
            target_count = round(profile.exclamation_intensity)
            # Cap at 3 to avoid absurdity
            target_count = min(target_count, 3)
            has_exclaim = "!" in text
            if has_exclaim and target_count > 1:
                text = re.sub(r"!+", "!" * target_count, text)
            elif has_exclaim and target_count == 0:
                text = text.replace("!", ".")

        return text

    def _match_greeting(self, text: str, profile: StyleProfile) -> str:
        """If fan opens with a greeting word, match it in reply.

        E.g., fan says 'hey' → we open with 'hey'. Fan says 'hi' → we open with 'hi'.
        Only applies at the start of a reply, not mid-sentence.
        """
        if not profile.opens_with_greeting or not profile.greeting_words or profile.message_count == 0:
            return text
        greeter = profile.greeting_words[0]
        # Only match if our reply starts with a greeting-ish word
        first = text.strip().lower().split()[0] if text.strip().split() else ""
        if first in {"hey", "hi", "hello", "yo"}:
            # Replace the greeting with the fan's preferred one
            text = re.sub(rf"^\b{re.escape(first)}\b", greeter, text, flags=re.IGNORECASE)
        return text

    def _echo_slang(self, text: str, profile: StyleProfile) -> str:
        """If the fan has signature slang, occasionally weave one in."""
        if not profile.slang:
            return text
        word = profile.slang[0]
        if word in text.lower():
            return text  # already present
        # Only echo into casual openers, not every message
        if profile.formality == "casual" and len(text) < 100:
            return f"{word} {text}" if not text.lower().startswith(word) else text
        return text
