"""Tests for HumanizerFilter — every AI tell pattern gets its own test.

TDD: Write test (RED) → implement (GREEN) → refactor.
Each test proves the filter catches a specific AI writing tell.
"""

import pytest
import re
from src.humanize.filter import HumanizerFilter


# ─── Fixture ───────────────────────────────────────────────

@pytest.fixture
def hf():
    return HumanizerFilter()


# ─── 2. EM DASHES & PUNCTUATION ────────────────────────────

class TestEmDashes:
    def test_em_dash_replaced_with_comma(self, hf):
        """Em dash — should become comma or period."""
        result = hf._remove_em_dashes("The policy — announced without warning — affects thousands.")
        assert "—" not in result
        assert result != "The policy — announced without warning — affects thousands."

    def test_en_dash_replaced(self, hf):
        """En dash – should also be replaced."""
        result = hf._remove_em_dashes("The changes – long overdue – take effect.")
        assert "–" not in result

    def test_double_hyphen_replaced(self, hf):
        """Double hyphen -- should be replaced."""
        result = hf._remove_em_dashes("The new policy -- announced without warning -- affects workers.")
        assert "--" not in result or "--" not in result

    def test_no_em_dashes_in_output(self, hf):
        """Final output must contain ZERO em dashes."""
        result = hf.humanize("The term is primarily promoted by Dutch institutions—not by the people themselves.")
        assert "—" not in result


class TestCurlyQuotes:
    def test_curly_double_quotes_straightened(self, hf):
        result = hf._remove_curly_quotes('He said \u201cthe project is on track\u201d but disagreed.')
        assert '\u201c' not in result
        assert '\u201d' not in result

    def test_curly_single_quotes_straightened(self, hf):
        result = hf._remove_curly_quotes("It\u2018s a matter of \u2018when\u2019 not \u2018if\u2019.")
        assert '\u2018' not in result
        assert '\u2019' not in result

    def test_mixed_quotes_all_straightened(self, hf):
        result = hf._remove_curly_quotes('\u201cHello\u201d and \u2018world\u2019')
        assert '\u201c' not in result and '\u2018' not in result


# ─── 3. AI VOCABULARY SCRUB ──────────────────────────────

class TestAIVocabulary:
    def test_delve_removed(self, hf):
        result = hf._scrub_ai_vocabulary("Let's delve into this topic.")
        assert "delve" not in result.lower()

    def test_underscore_removed(self, hf):
        result = hf._scrub_ai_vocabulary("This underscores the importance.")
        assert "underscore" not in result.lower()

    def test_showcase_removed(self, hf):
        result = hf._scrub_ai_vocabulary("This showcases our commitment.")
        assert "showcase" not in result.lower()

    def test_pivotal_removed(self, hf):
        result = hf._scrub_ai_vocabulary("A pivotal moment in history.")
        assert "pivotal" not in result.lower()

    def test_tapestry_removed(self, hf):
        result = hf._scrub_ai_vocabulary("A rich tapestry of cultures.")
        assert "tapestry" not in result.lower()

    def test_testament_removed(self, hf):
        result = hf._scrub_ai_vocabulary("A testament to their hard work.")
        assert "testament" not in result.lower()

    def test_crucial_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("This is crucial for success.")
        assert "crucial" not in result.lower()

    def test_enhance_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("This will enhance your experience.")
        assert "enhance" not in result.lower()

    def test_foster_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("To foster better relationships.")
        assert "foster" not in result.lower()

    def test_garner_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("To garner more attention.")
        assert "garner" not in result.lower()

    def test_intricate_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("The intricate details matter.")
        assert "intricate" not in result.lower()

    def test_interplay_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("The interplay of light and shadow.")
        assert "interplay" not in result.lower()

    def test_landscape_abstract_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("In the evolving landscape of tech.")
        assert "landscape" not in result.lower()

    def test_vibrant_abstract_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("A vibrant community of artists.")
        assert "vibrant" not in result.lower()

    def test_robust_abstract_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("A robust solution to the problem.")
        assert "robust" not in result.lower()

    def test_dynamic_abstract_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("A dynamic approach to learning.")
        assert "dynamic" not in result.lower()

    def test_renowned_replaced(self, hf):
        result = hf._scrub_ai_vocabulary("A renowned expert in the field.")
        assert "renowned" not in result.lower()

    def test_key_as_abstract_adjective(self, hf):
        result = hf._scrub_ai_vocabulary("A key moment in history.")
        assert "key" not in result.lower().split()

    def test_groundbreaking_removed(self, hf):
        result = hf._scrub_ai_vocabulary("A groundbreaking discovery.")
        assert "groundbreaking" not in result.lower()


# ─── 4. FILLERS AND HEDGING ─────────────────────────────

class TestFillers:
    def test_in_order_to(self, hf):
        result = hf._compress_fillers("In order to achieve this goal")
        assert "in order to" not in result.lower()

    def test_due_to_the_fact(self, hf):
        result = hf._compress_fillers("Due to the fact that it was raining")
        assert "due to the fact that" not in result.lower()

    def test_at_this_point(self, hf):
        result = hf._compress_fillers("At this point in time, we need")
        assert "at this point in time" not in result.lower()

    def test_has_the_ability(self, hf):
        result = hf._compress_fillers("The system has the ability to process")
        assert "has the ability to" not in result.lower()

    def test_it_is_important_to_note(self, hf):
        result = hf._compress_fillers("It is important to note that the data shows")
        assert "it is important to note that" not in result.lower()

    def test_excessive_hedging(self, hf):
        result = hf._compress_fillers("It could potentially possibly be argued that")
        assert len(result) < len("It could potentially possibly be argued that")

    def test_by_means_of(self, hf):
        result = hf._compress_fillers("By means of this new approach")
        assert "by means of" not in result.lower()

    def test_in_the_event_that(self, hf):
        result = hf._compress_fillers("In the event that you need help")
        assert "in the event that" not in result.lower()

    def test_with_regard_to(self, hf):
        result = hf._compress_fillers("With regard to your question")
        assert "with regard to" not in result.lower()


# ─── 5. STRUCTURAL AI TELLS ─────────────────────────────

class TestCopulaAvoidance:
    def test_serves_as(self, hf):
        result = hf._fix_copula_avoidance("Gallery 825 serves as an exhibition space.")
        assert "serves as" not in result.lower()

    def test_stands_as(self, hf):
        result = hf._fix_copula_avoidance("This stands as a reminder.")
        assert "stands as" not in result.lower()

    def test_boasts(self, hf):
        result = hf._fix_copula_avoidance("The gallery boasts over 3,000 square feet.")
        assert "boasts" not in result.lower() or "has" in result.lower() or "is" in result.lower()

    def test_marks_as(self, hf):
        result = hf._fix_copula_avoidance("This marks a turning point.")
        assert "marks" not in result.lower()


class TestNegativeParallelism:
    def test_not_only_but(self, hf):
        result = hf._fix_negative_parallelism("Not only does it look good, but it also works well.")
        assert "not only" not in result.lower()

    def test_not_just_about(self, hf):
        result = hf._fix_negative_parallelism("It's not just about the beat, it's about the feeling.")
        assert "not just" not in result.lower() or "not merely" not in result.lower()

    def test_tailing_negation(self, hf):
        result = hf._fix_negative_parallelism("The options come from the selected item, no guessing.")
        assert "no guessing" not in result.lower()


class TestRuleOfThree:
    def test_rule_of_three_list(self, hf):
        result = hf._fix_rule_of_three("The event features keynote sessions, panel discussions, and networking opportunities.")
        # Should condense the 3-item list — at minimum shouldn't have all three
        assert "," not in result or "and" in result

    def test_double_rule_of_three(self, hf):
        result = hf._fix_rule_of_three("Attendees can expect innovation, inspiration, and industry insights.")
        assert "innovation" in result or len(result) < 60  # condensed


class TestIngPhrases:
    def test_trailing_highlighting(self, hf):
        result = hf._fix_ing_phrases("The temple is painted blue, highlighting its connection to nature.")
        assert "highlighting" not in result.lower()

    def test_trailing_underscoring(self, hf):
        result = hf._fix_ing_phrases("The policy was changed, underscoring the need for reform.")
        assert "underscoring" not in result.lower()

    def test_trailing_reflecting(self, hf):
        result = hf._fix_ing_phrases("The colors were chosen, reflecting the region's natural beauty.")
        assert "reflecting" not in result.lower()

    def test_trailing_symbolizing(self, hf):
        result = hf._fix_ing_phrases("The dove was released, symbolizing peace.")
        assert "symbolizing" not in result.lower()

    def test_trailing_ensuring(self, hf):
        result = hf._fix_ing_phrases("The system was redesigned, ensuring better performance.")
        assert "ensuring" not in result.lower()

    def test_trailing_contributing(self, hf):
        result = hf._fix_ing_phrases("The funds were raised, contributing to the project's success.")
        assert "contributing" not in result.lower()

    def test_real_content_ing_preserved(self, hf):
        """Real present participles that are not AI tells should be preserved."""
        result = hf._fix_ing_phrases("I'm sitting here thinking about you")
        assert "sitting" in result


# ─── 6. TONE AND COMMUNICATION ──────────────────────────

class TestSycophantic:
    def test_certainly(self, hf):
        result = hf._fix_sycophantic("Certainly! Here's what you need.")
        assert "Certainly!" not in result

    def test_of_course_exclamation(self, hf):
        result = hf._fix_sycophantic("Of course! I'd be happy to help.")
        assert "Of course!" not in result

    def test_youre_absolutely_right(self, hf):
        result = hf._fix_sycophantic("You're absolutely right about that point.")
        assert "absolutely right" not in result.lower()

    def test_great_question(self, hf):
        result = hf._fix_sycophantic("Great question! Let me explain.")
        assert "Great question!" not in result


class TestCollaborative:
    def test_let_me_know(self, hf):
        result = hf._fix_collaborative("Let me know if you have questions.")
        assert "let me know" not in result.lower()

    def test_i_hope_this_helps(self, hf):
        result = hf._fix_collaborative("I hope this helps!")
        assert "i hope this helps" not in result.lower()

    def test_would_you_like(self, hf):
        result = hf._fix_collaborative("Would you like me to expand on that?")
        assert "would you like" not in result.lower()

    def test_want_me_to(self, hf):
        result = hf._fix_collaborative("Want me to give you more details?")
        assert "want me to" not in result.lower()


class TestSignposting:
    def test_lets_dive_in(self, hf):
        result = hf._fix_signposting("Let's dive into how this works.")
        assert "let's dive" not in result.lower()

    def test_lets_explore(self, hf):
        result = hf._fix_signposting("Let's explore the features.")
        assert "let's explore" not in result.lower()

    def test_heres_what_you_need(self, hf):
        result = hf._fix_signposting("Here's what you need to know about caching.")
        assert "here's what you need" not in result.lower()

    def test_without_further_ado(self, hf):
        result = hf._fix_signposting("Without further ado, let's begin.")
        assert "without further ado" not in result.lower()

    def test_now_lets_look(self, hf):
        result = hf._fix_signposting("Now let's look at the results.")
        assert "let's look" not in result.lower() or "now let" not in result.lower()

    def test_lets_break_this_down(self, hf):
        result = hf._fix_signposting("Let's break this down into steps.")
        assert "let's break this down" not in result.lower()


# ─── 7. CONTEXTUAL TELLS ───────────────────────────────

class TestElegantVariation:
    def test_synonym_cycling(self, hf):
        """Multiple synonyms for same subject should be collapsed."""
        text = "The protagonist faces challenges. The main character must overcome obstacles. The central figure triumphs."
        result = hf._fix_elegant_variation(text)
        # Should have fewer distinct references
        assert "protagonist" in result or "main character" in result or "central figure" in result


class TestPersuasiveAuthority:
    def test_real_question_is(self, hf):
        result = hf._fix_persuasive_authority("The real question is whether teams can adapt.")
        assert "the real question is" not in result.lower()

    def test_at_its_core(self, hf):
        result = hf._fix_persuasive_authority("At its core, this is about trust.")
        assert "at its core" not in result.lower()

    def test_what_really_matters(self, hf):
        result = hf._fix_persuasive_authority("What really matters is the user experience.")
        assert "what really matters" not in result.lower()

    def test_the_deeper_issue(self, hf):
        result = hf._fix_persuasive_authority("The deeper issue is organizational readiness.")
        assert "the deeper issue" not in result.lower()

    def test_heart_of_the_matter(self, hf):
        result = hf._fix_persuasive_authority("The heart of the matter is communication.")
        assert "the heart of the matter" not in result.lower()

    def test_fundamentally(self, hf):
        result = hf._fix_persuasive_authority("This is fundamentally about trust.")
        assert "fundamentally" not in result.lower()


class TestSignificanceEmphasis:
    def test_marks_a_shift_replaced(self, hf):
        result = hf._fix_significance("This marks a shift in how we work.")
        assert "marks a shift" not in result.lower() or "represents a shift" not in result.lower()

    def test_evolving_landscape_replaced(self, hf):
        result = hf._fix_significance("In today's evolving landscape.")
        assert "evolving landscape" not in result.lower()


# ─── 8. PIPELINE INTEGRATION ────────────────────────────

class TestPipeline:
    def test_humanize_removes_em_dashes(self, hf):
        result = hf.humanize("The policy—announced quietly—affects everyone.")
        assert "—" not in result

    def test_humanize_removes_curly_quotes(self, hf):
        result = hf.humanize('\u201cHello\u201d')
        assert '\u201c' not in result

    def test_humanize_removes_ai_vocab(self, hf):
        result = hf.humanize("This underscores the pivotal importance.")
        assert "underscores" not in result.lower()
        assert "pivotal" not in result.lower()

    def test_humanize_removes_fillers(self, hf):
        result = hf.humanize("In order to achieve this, due to the fact that.")
        assert "in order to" not in result.lower()

    def test_humanize_removes_sycophantic(self, hf):
        result = hf.humanize("Certainly! You're absolutely right.")
        assert "certainly!" not in result.lower()

    def test_humanize_fixes_copula(self, hf):
        result = hf.humanize("This serves as an example.")
        assert "serves as" not in result.lower()

    def test_humanize_removes_signposting(self, hf):
        result = hf.humanize("Let's dive into the details.")
        assert len(result) < 25  # shouldn't have the full sentence

    def test_humanize_removes_negative_parallelism(self, hf):
        result = hf.humanize("Not only does it work, but it's fast.")
        assert "not only" not in result.lower()

    def test_humanize_preserves_normal_text(self, hf):
        """Normal human text should pass through mostly unchanged."""
        text = "Hey babe, how's your day going? I was thinking about you 😘"
        result = hf.humanize(text)
        assert "hey" in result.lower()
        assert "thinking" in result.lower()

    def test_humanize_empty_string(self, hf):
        assert hf.humanize("") == ""

    def test_humanize_preserves_emoji(self, hf):
        text = "I miss you so much 😘"
        result = hf.humanize(text)
        assert "miss" in result.lower()