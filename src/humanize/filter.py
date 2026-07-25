"""HumanizerFilter — post-processing pipeline that removes AI writing tells.

Every outbound bot message flows through this before style mirroring.
Order matters: run humanizer FIRST, then style mirror.

Based on 33+ AI writing patterns from the humanizer skill (v2.9.1).
"""

import re


# ─── COMPILED PATTERNS ─────────────────────────────────

_EM_DASH_RE = re.compile(r"\u2014|\u2013|---|--")
_CURLY_DOUBLE_RE = re.compile(r"[\u201c\u201d]")
_CURLY_SINGLE_RE = re.compile(r"[\u2018\u2019]")

# AI vocabulary — words that are strong AI tells in abstract/salesy contexts
# Use \w* suffix to match conjugated forms (underscores, showcasing, etc.)
_AI_VOCABULARY = {
    "delve": "look",
    "underscore": "show",
    "showcase": "show",
    "pivotal": "important",
    "tapestry": "mix",          # abstract "tapestry of cultures" etc.
    "testament": "proof",
    "crucial": "important",
    "enhance": "improve",
    "foster": "build",
    "garner": "get",
    "intricate": "detailed",
    "interplay": "mix",
    "landscape": "world",       # abstract "landscape of tech" etc.
    "vibrant": "lively",       # only abstract "vibrant community" — keep literal
    "robust": "solid",         # only abstract
    "dynamic": "changing",     # only abstract
    "renowned": "famous",
    "groundbreaking": "new",
    "exemplify": "show",
    "indelible": "lasting",
    "transformative": "powerful",
    "bespoke": "custom",
    "leverage": "use",
    "holistic": "complete",
    "synergize": "work together",
    "actionable": "useful",
    "streamline": "simplify",
    "optimize": "improve",
    "facilitate": "help",
    "impactful": "strong",
    "meaningful": "real",
    "seamless": "smooth",
    "world-class": "great",
    "state-of-the-art": "modern",
}

# AI vocabulary with word-ending flexibility — use \w* when matching
_AI_VOCAB_WILDCARD = [
    (re.compile(r"\bunderscore\w*\b", re.IGNORECASE), "show"),
    (re.compile(r"\bshowcase\w*\b", re.IGNORECASE), "show"),
    (re.compile(r"\bgroundbreaking\b", re.IGNORECASE), "new"),
    (re.compile(r"\boptimiz\w+\b", re.IGNORECASE), "improve"),
    (re.compile(r"\bfacilitat\w+\b", re.IGNORECASE), "help"),
    (re.compile(r"\bleverag\w+\b", re.IGNORECASE), "use"),
    (re.compile(r"\bstreamlin\w+\b", re.IGNORECASE), "simplify"),
]

# Key as abstract adjective — only when followed by certain nouns
_KEY_ABSTRACT_RE = re.compile(
    r"\bkey\s+(moment|role|factor|element|component|aspect|feature|point|"
    r"player|figure|part|ingredient|driver|consideration|priority)\b",
    re.IGNORECASE,
)

# Filler phrases → replacements
_FILLERS = [
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because"),
    (re.compile(r"\bat this point in time\b", re.IGNORECASE), "now"),
    (re.compile(r"\bat the present time\b", re.IGNORECASE), "now"),
    (re.compile(r"\bhas the ability to\b", re.IGNORECASE), "can"),
    (re.compile(r"\bit is important to note that\b", re.IGNORECASE), ""),
    (re.compile(r"\bit should be noted that\b", re.IGNORECASE), ""),
    (re.compile(r"\bby means of\b", re.IGNORECASE), "by"),
    (re.compile(r"\bin the event that\b", re.IGNORECASE), "if"),
    (re.compile(r"\bwith regard to\b", re.IGNORECASE), "about"),
    (re.compile(r"\bin relation to\b", re.IGNORECASE), "about"),
    (re.compile(r"\bon the basis of\b", re.IGNORECASE), "based on"),
    (re.compile(r"\bin the vicinity of\b", re.IGNORECASE), "near"),
    (re.compile(r"\ba majority of\b", re.IGNORECASE), "most"),
    (re.compile(r"\ba number of\b", re.IGNORECASE), "some"),
    (re.compile(r"\bthe majority of\b", re.IGNORECASE), "most"),
]

# Excessive hedging patterns
_HEDGE_RE = re.compile(
    r"\b(could potentially|possibly maybe|it could be argued that|it might be said that|"
    r"it would seem that|it appears that|arguably|purportedly|ostensibly)\b",
    re.IGNORECASE,
)
_HEDGE_STACK_RE = re.compile(
    r"\b(potentially\s+possibly|possibly\s+potentially|could\s+possibly|may\s+possibly)\b",
    re.IGNORECASE,
)

# Copula avoidance patterns
_COPULA_REPLACEMENTS = [
    (re.compile(r"\bserves as\b", re.IGNORECASE), "is"),
    (re.compile(r"\bstands as\b", re.IGNORECASE), "is"),
    (re.compile(r"\bacts as\b", re.IGNORECASE), "is"),
    (re.compile(r"\bfunctions as\b", re.IGNORECASE), "is"),
    (re.compile(r"\bboasts?\b", re.IGNORECASE), "has"),
    (re.compile(r"\bmakes for\b", re.IGNORECASE), "is"),
    (re.compile(r"\bmarks?\s+(a|the)\b", re.IGNORECASE), "is a"),
]

# Negative parallelism (not only... but, not just... )
_NEG_PARALLEL_RE = re.compile(
    r"\b(not only|not just|not merely)\b.*?\b(but also|but rather|but)\b",
    re.IGNORECASE,
)

# Tailing negations: "no guessing", "no wasted motion", "no exceptions" at end
_TAIL_NEGATION_RE = re.compile(r",\s+(no\s+\w+)", re.IGNORECASE)

# Superficial -ing analysis phrases (trailing participle clauses)
_ING_PHRASE_RE = re.compile(
    r",\s*(highlighting|underscoring|emphasizing|reflecting|symbolizing|"
    r"ensuring|contributing to|cultivating|fostering|showcasing|"
    r"representing|demonstrating|illustrating|signifying|denoting)"
    r"\s+\w+[\w\s]*[.!]?$",
    re.IGNORECASE,
)

# Sycophantic/collaborative/servile language
_SYCOPHANTIC = [
    (re.compile(r"\bCertainly\b", re.IGNORECASE), "Sure"),
    (re.compile(r"\bOf course\b", re.IGNORECASE), "Sure"),
    (re.compile(r"\byou['']re absolutely right\b", re.IGNORECASE), "you're right"),
    (re.compile(r"\bGreat question\b", re.IGNORECASE), ""),
    (re.compile(r"\bExcellent question\b", re.IGNORECASE), ""),
    (re.compile(r"\bThat['']s a great point\b", re.IGNORECASE), "that's true"),
    (re.compile(r"\bI['']d be happy to\b", re.IGNORECASE), "I can"),
    (re.compile(r"\bI['']d love to help\b", re.IGNORECASE), "let me"),
]

_COLLABORATIVE = [
    (re.compile(r"\blet me know if\b", re.IGNORECASE), "if"),
    (re.compile(r"\bI hope this helps\b", re.IGNORECASE), ""),
    (re.compile(r"\bI hope that helps\b", re.IGNORECASE), ""),
    (re.compile(r"\bwould you like\b", re.IGNORECASE), "do you want"),
    (re.compile(r"\bwant me to\b", re.IGNORECASE), "should I"),
    (re.compile(r"\bdon['’]t hesitate to\b", re.IGNORECASE), "feel free to"),
    (re.compile(r"\bfeel free to reach out\b", re.IGNORECASE), "ask"),
    (re.compile(r"\bplease don['’]t hesitate\b", re.IGNORECASE), ""),
]

_SIGNPOSTING = [
    re.compile(r"\blet['’]s dive (in|into)\b", re.IGNORECASE),
    re.compile(r"\blet['’]s explore\b", re.IGNORECASE),
    re.compile(r"\blet['’]s break this down\b", re.IGNORECASE),
    re.compile(r"\bhere['’]s what you need to know\b", re.IGNORECASE),
    re.compile(r"\bwithout further ado\b", re.IGNORECASE),
    re.compile(r"\bnow let['’]s (look|take|examine)\b", re.IGNORECASE),
    re.compile(r"\bnow,? let['’]s\b", re.IGNORECASE),
    re.compile(r"\blet['’]s take a (look|closer look)\b", re.IGNORECASE),
    re.compile(r"\bhere['’]s the thing\b", re.IGNORECASE),
    re.compile(r"\bthe thing is\b", re.IGNORECASE),
    re.compile(r"\breal talk\b", re.IGNORECASE),
]

# Persuasive authority tropes
_PERSUASIVE = [
    (re.compile(r"\bthe real question is\b", re.IGNORECASE), "the question is"),
    (re.compile(r"\bat its core\b", re.IGNORECASE), ""),
    (re.compile(r"\bwhat really matters\b", re.IGNORECASE), "what matters"),
    (re.compile(r"\bthe deeper issue\b", re.IGNORECASE), "the issue"),
    (re.compile(r"\bthe heart of the matter\b", re.IGNORECASE), ""),
    (re.compile(r"\bfundamentally\b", re.IGNORECASE), ""),
    (re.compile(r"\bin reality\b", re.IGNORECASE), ""),
    (re.compile(r"\bwhen all is said and done\b", re.IGNORECASE), "ultimately"),
]

# Significance emphasis ("marks a shift", "evolving landscape", etc.)
_SIGNIFICANCE = [
    re.compile(r"\b(marks|represents|signals|heralds)\s+a\s+(shift|turning\s+point|milestone|new\s+era|new\s+chapter)\b", re.IGNORECASE),
    re.compile(r"\bevolving\s+landscape\b", re.IGNORECASE),
    re.compile(r"\brapidly\s+(evolving|changing)\s+(landscape|world|environment)\b", re.IGNORECASE),
    re.compile(r"\bstands?\s+(as|at)\s+(a|the)\s+(testament|reminder|symbol)\b", re.IGNORECASE),
    re.compile(r"\bsetting the stage for\b", re.IGNORECASE),
    re.compile(r"\bcontributing to the\b", re.IGNORECASE),
]

# Elegant variation (synonym cycling) — detect repeated reference to same entity
_ELEGANT_VAR_RE = re.compile(
    r"(\b\w+\b)(?:\s+\b\w+\b){0,5}\s+\1", re.IGNORECASE
)

# Rule of three pattern — "[item], [item], and [item]" near the end
_RULE_OF_THREE_RE = re.compile(
    r"((?:\w[\w']*\s*,\s*){1,3}(?:\w[\w']*)\s*,\s*and\s+\w[\w']*(?:\s+\w[\w']*){0,3}[.!?,]?)",
    re.IGNORECASE,
)

# Diff-anchored writing
_DIFF_ANCHOR_RE = re.compile(
    r"\b(was added to|was created to|is designed to|was implemented to|was changed to)\b",
    re.IGNORECASE,
)

# Knowledge-cutoff disclaimers
_CUTOFF_RE = re.compile(
    r"\b(as of\s+\d{4}|up to my last (training|update)|based on my (training|knowledge cutoff)"
    r"|my training data only goes up to|I was trained on data up to)\b",
    re.IGNORECASE,
)

# Speculative gap-fill
_SPECULATIVE_RE = re.compile(
    r"\b(likely\s+(grew\s+up|comes?\s+from|studied|attended|began|started)"
    r"|maintains?\s+a\s+low\s+profile|keeps?\s+(personal|private)\s+details?\s+private"
    r"|prefers?\s+to\s+stay\s+out\s+of\s+the\s+spotlight|it\s+is\s+believed\s+that)\b",
    re.IGNORECASE,
)

# Staccato drama detection (3+ short sentences in a row, each < 20 chars)
_STACCATO_RE = re.compile(r"(?:[.!?]\s+)([\"']?[A-Z][^.?!]{3,20}[.!?]){2,}", re.MULTILINE)


class HumanizerFilter:
    """Pipeline of pattern-removing transforms. Each _method tackles one tell category.

    Usage:
        hf = HumanizerFilter()
        clean = hf.humanize("The policy — announced without warning — affects thousands.")
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.transforms = [
            ("em_dashes", self._remove_em_dashes),
            ("curly_quotes", self._remove_curly_quotes),
            ("ai_vocab", self._scrub_ai_vocabulary),
            ("fillers", self._compress_fillers),
            ("copula", self._fix_copula_avoidance),
            ("neg_parallel", self._fix_negative_parallelism),
            ("rule_of_three", self._fix_rule_of_three),
            ("ing_phrases", self._fix_ing_phrases),
            ("elegant_var", self._fix_elegant_variation),
            ("sycophantic", self._fix_sycophantic),
            ("collaborative", self._fix_collaborative),
            ("signposting", self._fix_signposting),
            ("persuasive", self._fix_persuasive_authority),
            ("significance", self._fix_significance),
            ("speculative", self._fix_speculative),
        ]

    def humanize(self, text: str) -> str:
        """Run all transforms in order. Returns humanized text."""
        if not self.enabled or not text:
            return text
        out = text
        for _name, transform in self.transforms:
            out = transform(out)
        # Clean up double spaces and leading/trailing whitespace from removals
        out = re.sub(r" {2,}", " ", out).strip()
        return out

    # ─── 2. PUNCTUATION TELLS ──────────────────────────

    def _remove_em_dashes(self, text: str) -> str:
        """Replace em/en dashes and double hyphens with commas or restructure."""
        # Spaced em dash: "word — word" → "word, word"
        text = re.sub(r"\s+[\u2014\u2013]\s+", ", ", text)
        # Spaced double hyphen: "word -- word" → "word, word"
        text = re.sub(r"\s+--\s+", ", ", text)
        # Unspaced: "word—word" → "word, word"
        text = re.sub(r"([a-zA-Z.,!?])\u2014([a-zA-Z])", r"\1, \2", text)
        text = re.sub(r"([a-zA-Z.,!?])\u2013([a-zA-Z])", r"\1, \2", text)
        text = re.sub(r"([a-zA-Z.,!?])--([a-zA-Z])", r"\1, \2", text)
        return text

    def _remove_curly_quotes(self, text: str) -> str:
        """Replace curly/smart quotes with straight quotes."""
        text = _CURLY_DOUBLE_RE.sub('"', text)
        text = _CURLY_SINGLE_RE.sub("'", text)
        return text

    # ─── 3. AI VOCABULARY ──────────────────────────────

    def _scrub_ai_vocabulary(self, text: str) -> str:
        """Replace overused AI vocabulary with simpler alternatives."""
        out = text
        for word, replacement in _AI_VOCABULARY.items():
            # Case-insensitive whole-word replacement
            out = re.sub(rf"\b{re.escape(word)}\b", replacement, out, flags=re.IGNORECASE)
        # Wildcard patterns (handles variations like underscores, showcasing)
        for pattern, replacement in _AI_VOCAB_WILDCARD:
            out = pattern.sub(replacement, out)
        # Key as abstract adjective
        out = _KEY_ABSTRACT_RE.sub(r"important \1", out)
        # Remove "boasts of/a" as abstract (already done by copula fix)
        return out

    # ─── 4. FILLERS & HEDGING ─────────────────────────

    def _compress_fillers(self, text: str) -> str:
        """Compress wordy filler phrases into simpler alternatives."""
        out = text
        for pattern, replacement in _FILLERS:
            out = pattern.sub(replacement, out)
        # Hedge stacking
        out = _HEDGE_STACK_RE.sub("could", out)
        # General hedging
        out = _HEDGE_RE.sub("", out)
        return out

    # ─── 5. STRUCTURAL TELLS ──────────────────────────

    def _fix_copula_avoidance(self, text: str) -> str:
        """Replace 'serves as' → 'is', 'boasts' → 'has', etc."""
        out = text
        for pattern, replacement in _COPULA_REPLACEMENTS:
            out = pattern.sub(replacement, out)
        return out

    def _fix_negative_parallelism(self, text: str) -> str:
        """Fix 'not only... but also' constructions."""
        out = text
        # Match "not only X but (also) Y" — simplify to "X and Y"
        out = _NEG_PARALLEL_RE.sub("", out)
        # Handle standalone "not just X, it's Y" patterns
        out = re.sub(
            r"\bit['’]s\s+not\s+(just|merely|only)\s+",
            "it's ",
            out,
            flags=re.IGNORECASE,
        )
        # Handle "Not only does X, it also Y" → "X and Y"
        out = re.sub(
            r"\bnot only\s+(do|does|did|is|are|was|were)\s+",
            "",
            out,
            flags=re.IGNORECASE,
        )
        out = re.sub(r"\bbut\s+(also|rather)\b", "and", out, flags=re.IGNORECASE)
        # Tailing negations
        out = _TAIL_NEGATION_RE.sub("", out)
        return out

    def _fix_rule_of_three(self, text: str) -> str:
        """Condense rule-of-three lists where they feel formulaic."""
        out = text
        # Find 3-item lists: "A, B, and C"
        match = _RULE_OF_THREE_RE.search(out)
        if match:
            items = [x.strip() for x in re.split(r",\s*", match.group(1))]
            items = [re.sub(r"^\s*and\s+", "", it) for it in items]
            if len(items) >= 3:
                # Keep first two items joined with "and"
                condensed = f"{items[0]} and {items[1]}"
                out = out[:match.start()] + condensed + out[match.end() :]
        return out

    def _fix_ing_phrases(self, text: str) -> str:
        """Remove trailing superficial -ing analysis clauses."""
        out = text
        # Match trailing ", highlighting X", ", reflecting Y" etc.
        out = _ING_PHRASE_RE.sub("", out)
        # Also handle mid-sentence: "..., highlighting X, ..."
        out = re.sub(
            r",\s*(highlighting|underscoring|emphasizing|reflecting|symbolizing|"
            r"ensuring|contributing to|cultivating|fostering|showcasing|"
            r"representing|demonstrating|illustrating|signifying|denoting)"
            r"\s+\w+[\w\s]*,?\s*",
            ", ",
            out,
            flags=re.IGNORECASE,
        )
        return out

    # ─── 6. TONE & COMMUNICATION ──────────────────────

    def _fix_sycophantic(self, text: str) -> str:
        """Remove overly eager/servile language."""
        out = text
        for pattern, replacement in _SYCOPHANTIC:
            out = pattern.sub(replacement, out)
        return out

    def _fix_collaborative(self, text: str) -> str:
        """Remove collaborative chatbot language."""
        out = text
        for pattern, replacement in _COLLABORATIVE:
            out = pattern.sub(replacement, out)
        return out

    def _fix_signposting(self, text: str) -> str:
        """Remove meta-commentary signposting phrases."""
        out = text
        for pattern in _SIGNPOSTING:
            out = pattern.sub("", out)
        return out

    # ─── 7. CONTEXTUAL TELLS ──────────────────────────

    def _fix_elegant_variation(self, text: str) -> str:
        """Collapse synonym cycling where same entity is referred to differently."""
        # This is a simplified approach — detect repeated adjacent sentences
        # about the same subject with different descriptors
        out = text
        # Detect: "The protagonist did X. The main character did Y. The central figure did Z."
        # Replace all but the first reference with pronouns
        subject_synonyms = [
            (r"\b(the\s+)?protagonist\b", r"\b(the\s+)?main\s+character\b", r"\b(the\s+)?central\s+figure\b", r"\b(the\s+)?hero\b"),
        ]
        for syn_set in subject_synonyms:
            # Find first occurrence of any synonym
            first = None
            for syn in syn_set:
                m = re.search(syn, out, re.IGNORECASE)
                if m and (first is None or m.start() < first.start()):
                    first = m
            if first:
                # Replace subsequent occurrences with appropriate pronoun
                for syn in syn_set:
                    # Replace second+ occurrence with "they"
                    parts = out.split(syn, 2)
                    if len(parts) == 3:
                        out = parts[0] + syn + parts[1] + " they " + parts[2].strip()
                        break
        return out

    def _fix_persuasive_authority(self, text: str) -> str:
        """Remove persuasive authority tropes."""
        out = text
        for pattern, replacement in _PERSUASIVE:
            out = pattern.sub(replacement, out)
        return out

    def _fix_significance(self, text: str) -> str:
        """Remove undue emphasis on significance."""
        out = text
        for pattern in _SIGNIFICANCE:
            out = pattern.sub("", out)
        return out

    def _fix_speculative(self, text: str) -> str:
        """Remove speculative gap-fill and knowledge-cutoff disclaimers."""
        out = text
        out = _CUTOFF_RE.sub("", out)
        out = _SPECULATIVE_RE.sub("", out)
        # Diff-anchored writing
        out = _DIFF_ANCHOR_RE.sub("", out)
        return out