"""
Fansly AI Bot Orchestrator — Ties all 17 systems to the apifansly.com API.

This is the main chat loop: poll chats → process messages → send replies.
Every message flows through the persona, funnel, script, NLP, reciprocity,
aftercare, and tier systems before a response is generated.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from .fansly_client import ApifanslyClient, FanslyApiClient, FanslyConfig, ChatInfo, MessageInfo
from .persona.loader import PersonaLoader
from .persona.validator import PersonaValidator
from .funnel.spiral import SpiralStateMachine, SpiralPhase
from .funnel.session import FanSession
from .notes.repository import FanNoteRepository
from .notes.models import FanNote
from .notes.extractor import NoteExtractor
from .memory.store import MessageStore
from .memory.llm import LLMFactExtractor
from .profiling.classifier import FanClassifier
from .rhythm.engine import PushPullEngine
from .scripts.loader import ScriptLibrary
from .scripts.engine import ScriptEngine, ScriptCategory
from .tiers.classifier import TierClassifier
from .churn.predictor import ChurnPredictor
from .reciprocity.engine import ReciprocityEngine
from .nlp.triggers import NLPTriggerEngine
from .aftercare.engine import AftercareEngine
from .timing.delays import DelayManager
from .objections.dispatcher import ObjectionDispatcher
from .analytics.dashboard import KPIDashboard
from .style.mirror import StyleMirror, StyleProfile
from .sequences.repository import SequenceRepository
from .sequences.engine import SequenceEngine
from .sequences.models import StepStatus
from .humanize.filter import HumanizerFilter
from .humanize.variation import VariationPool

logger = logging.getLogger(__name__)


class FanslyBot:
    """Main orchestrator for the Fansly AI chatbot."""

    def __init__(
        self,
        client: FanslyApiClient,
        persona_loader: PersonaLoader,
        note_repo: FanNoteRepository,
        creator_id: str = "sunny_charm",
        message_store: Optional[MessageStore] = None,
        fact_extractor: Optional[LLMFactExtractor] = None,
    ):
        self.client = client
        self.creator_id = creator_id
        self.account_id = client.config.account_id

        # Load persona + validator for voice consistency
        self.persona = persona_loader.load(creator_id)
        self.validator = PersonaValidator(self.persona)

        # Track active fan sessions (fan_id -> FanSession)
        self.sessions: dict[str, FanSession] = {}
        self.note_repo = note_repo

        # PPV Sequence System
        self.sequence_repo = SequenceRepository(db_url=self.note_repo.engine.url.render_as_string(hide_password=False) if hasattr(self.note_repo.engine.url, 'render_as_string') else str(self.note_repo.engine.url))

        # Memory: persistent history + LLM fact extraction
        self.message_store = message_store
        self.fact_extractor = fact_extractor
        self.note_extractor = NoteExtractor(llm_client=None)  # merge() only
        self._extract_counters: dict[str, int] = {}

        # 17-system components
        self.classifier = FanClassifier()
        self.rhythm_engines: dict[str, PushPullEngine] = {}
        self.script_library = ScriptLibrary()
        self.script_library.load_builtin()
        self.script_engine = ScriptEngine(self.script_library)
        self.tier_classifier = TierClassifier()
        self.churn_predictor = ChurnPredictor()
        self.reciprocity = ReciprocityEngine()
        self.nlp_engine = NLPTriggerEngine()
        self.aftercare = AftercareEngine()
        self.delays = DelayManager()
        self.objections = ObjectionDispatcher()
        self.kpi = KPIDashboard()

        # Dynamic style mirroring — adapts reply mechanics to each fan's writing
        self.style_mirror = StyleMirror()
        self._style_profiles: dict[str, StyleProfile] = {}

        # Humanizer — strips AI writing tells from every outbound message
        self.humanizer = HumanizerFilter(enabled=True)

        # Variation pool — eliminates message repetition with 5-8 variants per type
        self.variation = VariationPool()

        # PPV Sequence Engine — ordered vault media ladders
        self.sequence_engine = SequenceEngine(self.sequence_repo, creator_id)

        # Bot on/off toggle — poll_and_process() returns early when disabled
        self.enabled = True

        # Track known purchase counts per fan to detect new purchases
        self._purchase_count_cache: dict[str, int] = {}
        # Initialize cache from existing fan notes to prevent false advance_level on restart
        self._init_purchase_cache()

        # Message deduplication: track processed message_ids per fan
        # Prevents re-processing messages already handled (fixes C1 bug)
        self._processed_message_ids: dict[str, set[str]] = {}
        self._max_dedup_entries = 1000  # LRU eviction threshold

    # ─── MAIN LOOP ──────────────────────────────────────

    def poll_and_process(self, filter_type: str = "all", max_chats: int = 50):
        """Main loop: fetch chats, process unread messages, send replies."""
        if not self.enabled:
            logger.debug("Bot disabled — skipping poll cycle")
            return
        chats = self.client.get_all_chats(filter_type=filter_type)
        logger.info(f"Processing {len(chats)} chats")

        for chat in chats[:max_chats]:
            try:
                self._process_chat(chat)
            except Exception as e:
                logger.error(f"Error processing chat {chat.chat_id}: {e}")

    def toggle(self, force: Optional[bool] = None) -> bool:
        """Toggle bot on/off. Returns new enabled state.

        If force is True/False, set to that state; otherwise flip.
        """
        if force is not None:
            self.enabled = bool(force)
        else:
            self.enabled = not self.enabled
        logger.info(f"Bot {'enabled' if self.enabled else 'disabled'}")
        return self.enabled

    def _process_chat(self, chat: ChatInfo):
        """Process one chat: read messages, decide action, reply."""
        fan_id = chat.partner_account_id

        # Get or create fan session
        if fan_id not in self.sessions:
            self.sessions[fan_id] = FanSession(
                fan_id=fan_id, creator_id=self.creator_id
            )

        # Get fan notes
        note = self.note_repo.get(fan_id, self.creator_id)
        if note is None:
            note = FanNote(fan_id=fan_id, creator_id=self.creator_id)

        # Get new messages
        messages, _ = self.client.list_messages(chat.chat_id, limit=10)
        unread = [m for m in messages if m.is_from_fan]

        if not unread:
            return

        # Classify fan personality from first messages
        if not self._has_classified(fan_id):
            fan_texts = [m.content for m in messages[-5:] if m.is_from_fan]
            result = self.classifier.classify(fan_texts)
            note = FanNote(
                fan_id=fan_id,
                creator_id=self.creator_id,
                relationship_stage=f"classified_{result.personality_type}",
            )
            self.note_repo.save(note)
            logger.info(f"Fan {fan_id} classified as {result.personality_type}")

        # Process the most recent unread message
        latest = unread[-1]

        # Message dedup: skip if already processed (fixes C1 — repeating replies)
        if self._has_processed(fan_id, latest.message_id):
            logger.debug(f"Skipping already-processed message {latest.message_id} for {fan_id}")
            return
        self._mark_processed(fan_id, latest.message_id)

        session = self.sessions[fan_id]
        session.add_message("subscriber", latest.content)

        # Persist fan message to long-term memory
        if self.message_store:
            try:
                self.message_store.save_message(
                    fan_id, self.creator_id, "fan", latest.content, latest.message_id
                )
            except Exception as e:
                logger.error(f"Failed to persist fan message: {e}")

        # Periodic fact extraction: every 3rd fan message, batch-extract from recent history
        if (
            self.fact_extractor
            and self.fact_extractor.enabled
            and self.message_store
        ):
            count = self._extract_counters.get(fan_id, 0) + 1
            self._extract_counters[fan_id] = count
            if count >= 3:
                self._extract_counters[fan_id] = 0
                try:
                    recent = self.message_store.get_history(fan_id, self.creator_id, limit=8)
                    fan_texts = [m["content"] for m in recent if m["sender"] == "fan"]
                    extracted = self.fact_extractor.extract(fan_texts)
                    if extracted:
                        note = self.note_extractor.merge(note, extracted)
                        self.note_repo.save(note)
                        logger.info(f"Learned about {fan_id}: {list(extracted.keys())}")
                except Exception as e:
                    logger.error(f"Fact extraction error for {fan_id}: {e}")

        # ─── DECISION PIPELINE ───────────────────────────

        # 0. Initialize purchase cache on first contact
        if fan_id not in self._purchase_count_cache:
            self._purchase_count_cache[fan_id] = note.purchase_count if note else 0

        # Check if fan made a new purchase since last check
        purchase_detected = False
        if note and note.purchase_count > self._purchase_count_cache.get(fan_id, 0):
            self._purchase_count_cache[fan_id] = note.purchase_count
            purchase_detected = True
            # Advance spiral level
            session.funnel.advance_level()
            # Mark all active sequences as purchased at current step
            for seq in self.sequence_repo.list_sequences(active_only=True):
                progress = self.sequence_repo.get_progress(fan_id, seq.id, self.creator_id)
                if progress and progress.status == StepStatus.SENT:
                    self.sequence_engine.mark_purchased(fan_id, seq.id)
                    logger.info(f"Detected purchase by {fan_id}, advanced sequence + spiral level")

        # Check ghosting: if fan hasn't messaged in 48h+, enter warmup
        if session.last_activity and not session.funnel.is_warmup:
            hours_since = (datetime.now(timezone.utc) - session.last_activity).total_seconds() / 3600
            if hours_since > 48:
                session.funnel.enter_warmup()
                logger.info(f"Fan {fan_id} returned after ghost — warmup mode")

        # If warmup and fan sent a positive message, exit warmup
        if session.funnel.is_warmup and latest.content:
            positive_words = ["yes", "yeah", "sure", "ok", "miss", "hey", "hi", "hello", "how are", "good"]
            if any(w in latest.content.lower() for w in positive_words):
                session.funnel.exit_warmup()
                logger.info(f"Fan {fan_id} responded positively — warmup complete")

        # Track rejection: fan said no in OFFER or HANDLE phase
        funnel_spiral = session.funnel
        if funnel_spiral.current_stage in (SpiralPhase.OFFER, SpiralPhase.HANDLE):
            rejection_keywords = ["no", "not", "can't", "cant", "broke", "don't have", "too much", "expensive", "pass"]
            if any(kw in latest.content.lower() for kw in rejection_keywords):
                funnel_spiral.record_rejection()
                logger.info(f"Fan {fan_id} rejected PPV in {funnel_spiral.current_stage.value} — rejection {funnel_spiral.consecutive_rejections}")

        # Cooldown exit on engagement signals
        if funnel_spiral.cooldown:
            flirty_keywords = ["hard", "horny", "wet", "turn on", "hot", "sexy", "want you",
                               "cum", "fuck", "dick", "pussy", "cock", "ass", "boob", "tits",
                               "miss you", "need you", "craving"]
            exited_cooldown = False
            if any(kw in latest.content.lower() for kw in flirty_keywords):
                funnel_spiral.exit_cooldown()
                exited_cooldown = True
                logger.info(f"Fan {fan_id} sent flirty message — cooldown exited")
            # Also exit cooldown if fan is tipping
            if latest.total_tip > 0:
                funnel_spiral.exit_cooldown()
                exited_cooldown = True
                logger.info(f"Fan {fan_id} tipped — cooldown exited")
            if not exited_cooldown:
                # Cooldown active: limit sales energy — stay in rapport
                if funnel_spiral.current_stage in (SpiralPhase.OFFER, SpiralPhase.HANDLE):
                    try:
                        funnel_spiral.transition(SpiralPhase.RAPPORT)
                    except ValueError:
                        pass
                    logger.debug(f"Cooldown active for {fan_id} — staying in light rapport")

        # 1. Check if we're in aftercare mode — only if spiral phase allows it
        if funnel_spiral.current_stage in (SpiralPhase.CLOSE, SpiralPhase.AFTERCARE) and self.aftercare.is_aftercare_due(fan_id):
            self._send_aftercare(chat.chat_id, fan_id)
            return

        # 2. Check churn risk
        risk = self.churn_predictor.calculate_risk(
            days_since_last_purchase=self._days_since_last_purchase(note),
            days_since_last_message=0,  # they just messaged
            sentiment_score=0.5,  # neutral default
        )
        if risk > 0.6:
            self._send_reengagement(chat.chat_id, fan_id, risk)
            return

        # 3. Check if reciprocity premium is ready
        if self.reciprocity.is_premium_ready(fan_id):
            self._send_premium_ppv(chat.chat_id, fan_id, note)
            return

        # 4. Generate contextual reply based on funnel stage
        reply = self._generate_reply(
            chat.chat_id, fan_id, latest, session, note
        )

        if reply:
            # Validate persona before sending
            validation = self.validator.validate(reply)
            if not validation.passed:
                logger.warning(
                    f"Persona violation for {fan_id}: {validation.violations}"
                )
                # Fix: strip forbidden phrases
                for phrase in self.persona.forbidden_phrases:
                    reply = reply.replace(phrase, self.persona.pet_names[0] if self.persona.pet_names else "babe")

            styled_reply = self._styled_send(chat.chat_id, fan_id, reply)
            session.add_message("creator", styled_reply)
            logger.info(f"Replied to {fan_id}: {styled_reply[:50]}...")

    # ─── REPLY GENERATION ───────────────────────────────

    def _generate_reply(
        self,
        chat_id: str,
        fan_id: str,
        message: MessageInfo,
        session: FanSession,
        note: FanNote,
    ) -> Optional[str]:
        """Generate a context-aware reply using the full system pipeline."""
        funnel = session.funnel
        context = {
            "fan_notes": note.model_dump() if note else {},
            "rapport_count": funnel.phase_history.count(SpiralPhase.RAPPORT),
            "purchase_count": note.purchase_count if note else 0,
            "total_spent": note.total_spent if note else 0,
            "history": (
                self.message_store.get_recent_context(fan_id, self.creator_id, limit=10)
                if self.message_store
                else ""
            ),
            "known_facts": note.facts if note else [],
        }

        # Get push-pull engine for this fan
        if fan_id not in self.rhythm_engines:
            self.rhythm_engines[fan_id] = PushPullEngine()
        rhythm = self.rhythm_engines[fan_id]

        # Analyze fan message for push-pull signals
        analysis = rhythm.analyze_fan_message(message.content)

        # ─── Stage-based routing ─────────────────────────

        if funnel.current_stage == SpiralPhase.RAPPORT:
            if funnel.min_messages_before_tease() == 0 and analysis.ready_for_tease:
                # Fan is ready — move to tease stage
                funnel.transition(SpiralPhase.TEASE)
                scripts = self.script_library.get_by_category(ScriptCategory.PPV_SOFT_TEASE)
                if scripts:
                    return self.script_engine.resolve(scripts[0], context)[0]

            # Stay in rapport — pick push or pull
            rhythm.next()
            if rhythm.current_phase.value == "push":
                # Send flirtatious spike
                return self._generate_push_message(note)

            # Pull: use NLP thought-of-you or basic rapport
            thought = self.nlp_engine.generate_thought_of_you(
                {"interests": note.preferences if note else []}
            )
            if thought:
                return thought

            # Default rapport reply
            return self.variation.pick("rapport")

        elif funnel.current_stage == SpiralPhase.TEASE:
            # Check if fan is ready for offer
            if analysis.ready_for_tease:
                funnel.transition(SpiralPhase.OFFER)
                scripts = self.script_library.get_by_category(ScriptCategory.PPV_SOFT_TEASE)
                if scripts and len(scripts[0].messages) > 1:
                    return self.script_engine.resolve(scripts[0], context)[1]

            return self._generate_push_message(note)

        elif funnel.current_stage == SpiralPhase.OFFER:
            # Send PPV offer — use sequence engine to find next PPV
            if funnel.can_send_ppv():
                result = self.sequence_engine.get_next_ppv(fan_id, "offer", fan_total_spent=note.total_spent if note else 0)
                if result:
                    seq, step = result
                    # Send tease script first
                    if step.tease_script:
                        self._styled_send(chat_id, fan_id, step.tease_script)
                    else:
                        self._styled_send(chat_id, fan_id, self.variation.pick("push"))

                    # Send actual PPV with vault media
                    self._send_ppv_with_media(chat_id, fan_id, seq, step, note)
                    return None  # Already sent, nothing else to return

                # Fallback to generic script if no sequence configured
                scripts = self.script_library.get_by_category(ScriptCategory.PPV_SOFT_TEASE)
                if scripts and len(scripts[0].messages) > 2:
                    return self.script_engine.resolve(scripts[0], context)[2]

        elif funnel.current_stage == SpiralPhase.HANDLE:
            # Classify objection and route
            objection_type = self.objections.classify_objection(message.content)
            handler_name = self.objections.get_handler(objection_type)
            script = self.script_library.get(handler_name)
            if script:
                return self.script_engine.resolve(script, context)[0]

        elif funnel.current_stage == SpiralPhase.CLOSE:
            # Close → transition to aftercare, which will loop to RAPPORT at next level
            funnel.transition(SpiralPhase.AFTERCARE)
            return self.variation.pick("close")

        # Fallback
        return self._generate_push_message(note)

    # ─── HELPERS ────────────────────────────────────────

    def _profile_for(self, fan_id: str) -> StyleProfile:
        """Compute/refresh a fan's style profile from stored history."""
        if self.message_store:
            try:
                history = self.message_store.get_history(fan_id, self.creator_id, limit=30)
                fan_texts = [m["content"] for m in history if m["sender"] == "fan"]
                if fan_texts:
                    profile = self.style_mirror.analyze(fan_texts)
                    self._style_profiles[fan_id] = profile
                    return profile
            except Exception as e:
                logger.error(f"Style analysis failed for {fan_id}: {e}")
        return self._style_profiles.get(fan_id, StyleProfile())

    def _styled_send(self, chat_id: str, fan_id: str, text: str) -> str:
        """Adapt text to the fan's writing style, send it, persist it.

        Returns the styled text actually sent (for session/logging).
        Every outbound message flows through here so style mirroring and
        memory persistence are guaranteed for all message types.
        """
        profile = self._profile_for(fan_id)
        # Humanize first (remove AI tells), then style mirror (adapt to fan)
        humanized = self.humanizer.humanize(text)
        styled = self.style_mirror.adapt(
            humanized if humanized else text,  # fallback if humanizer returns empty
            profile,
            common_typos=self.persona.common_typos,
            pet_names=self.persona.pet_names,
        )
        self.client.send_message(chat_id, styled)
        if self.message_store:
            try:
                self.message_store.save_message(fan_id, self.creator_id, "creator", styled)
            except Exception as e:
                logger.error(f"Failed to persist styled reply: {e}")
        return styled

    def _generate_push_message(self, note: Optional[FanNote]) -> str:
        """Generate a flirtatious push spike, personalized with remembered facts."""
        if note and note.facts:
            # Reference the most recently learned fact — shows we remembered
            fact = note.facts[-1]
            return f"I was just thinking about you... especially after what you told me about {fact} 😏"
        if note and note.preferences:
            return self.variation.pick("push")
        return self.variation.pick("push")

    def _send_aftercare(self, chat_id: str, fan_id: str):
        """Send aftercare sequence after a purchase, then loop back to RAPPORT at next level."""
        plan = self.aftercare.trigger_aftercare(50.0, fan_id)  # TODO: get actual amount
        if "thanks" in plan.actions:
            self._styled_send(chat_id, fan_id, self.variation.pick("aftercare"))
        self.aftercare.mark_aftercare_sent(fan_id)
        # Complete the spiral: AFTERCARE → RAPPORT at next escalation level
        sess = self.sessions.get(fan_id)
        if sess:
            try:
                sess.funnel.complete_aftercare()
                logger.info(f"Spiral: aftercare complete for {fan_id}, back to RAPPORT at level {sess.funnel.level.number}")
            except Exception:
                pass

    def _send_reengagement(self, chat_id: str, fan_id: str, risk: float):
        """Send re-engagement message for at-risk fans."""
        intervention = self.churn_predictor.get_intervention(risk)
        if intervention == "reengage_soft":
            self._styled_send(chat_id, fan_id, self.variation.pick("reengage_soft"))
        elif intervention in ("reengage_hard", "win_back"):
            self._styled_send(chat_id, fan_id, self.variation.pick("reengage_hard"))
        self.churn_predictor.mark_reengaged(fan_id)

    def _send_premium_ppv(self, chat_id: str, fan_id: str, note: FanNote):
        """Send premium PPV offer when reciprocity debt is ready."""
        base_price = 25.0
        premium = self.reciprocity.suggest_premium_price(fan_id, base_price)
        # Find a whale or premium sequence for this fan
        result = self.sequence_engine.get_next_ppv(fan_id, "offer", fan_total_spent=note.total_spent if note else 0)
        if result:
            seq, step = result
            if step.price >= 25 or step.offer_script:
                self._send_ppv_with_media(chat_id, fan_id, seq, step, note)
                self.reciprocity.mark_premium_pitched(fan_id)
                return

        # Fallback if no premium sequence configured
        self._styled_send(
            chat_id, fan_id,
            self.variation.pick("premium_ppv"),
        )
        self.reciprocity.mark_premium_pitched(fan_id)

    def _send_ppv_with_media(self, chat_id: str, fan_id: str, seq, step, note):
        """Send a PPV message with actual vault media attached.

        Uses the send_ppv method on the Fansly client with the step's
        media_id and price. Marks the step as sent in the engine.
        """
        try:
            # Use the step's offer script or a default teaser
            offer_text = step.offer_script or f"You're gonna love this... 🔥"
            styled = self._styled_send(chat_id, fan_id, offer_text)
            # Send the actual PPV media
            self.client.send_ppv(
                chat_id=chat_id,
                content=styled,
                media_id=step.media_id,
                price=step.price,
                preview_id=step.preview_id,
            )
            # Mark as sent in the engine
            self.sequence_engine.mark_sent(fan_id, seq, step)
            logger.info(f"Sent PPV {step.media_id} (${step.price}) to {fan_id} in seq {seq.name}")
        except Exception as e:
            logger.error(f"Failed to send PPV to {fan_id}: {e}")

    def _days_since_last_purchase(self, note: Optional[FanNote]) -> int:
        if not note or not note.last_purchase_at:
            return 90  # default: treat as lapsed
        from datetime import datetime, timezone
        delta = datetime.now(timezone.utc) - note.last_purchase_at
        return delta.days

    def _has_classified(self, fan_id: str) -> bool:
        note = self.note_repo.get(fan_id, self.creator_id)
        return note is not None and note.relationship_stage.startswith("classified_")

    def _init_purchase_cache(self):
        """Initialize purchase_count cache from all stored fan notes.
        Prevents false advance_level() on bot restart."""
        try:
            from .notes.repository import FAN_NOTES_TABLE, _row_to_note
            with self.note_repo.engine.connect() as c:
                rows = c.execute(
                    FAN_NOTES_TABLE.select().where(FAN_NOTES_TABLE.c.creator_id == self.creator_id)
                ).fetchall()
            for row in rows:
                try:
                    note = _row_to_note(row)
                    self._purchase_count_cache[note.fan_id] = note.purchase_count
                except Exception:
                    pass
            logger.info(f"Purchase cache initialized with {len(self._purchase_count_cache)} fans")
        except Exception as e:
            logger.warning(f"Could not initialize purchase cache: {e}")

    # ─── MESSAGE DEDUPLICATION ──────────────────────────

    def _has_processed(self, fan_id: str, message_id: str) -> bool:
        """Check if a message has already been processed."""
        return fan_id in self._processed_message_ids and message_id in self._processed_message_ids[fan_id]

    def _mark_processed(self, fan_id: str, message_id: str):
        """Mark a message as processed. LRU eviction at max_dedup_entries."""
        if fan_id not in self._processed_message_ids:
            self._processed_message_ids[fan_id] = set()
        self._processed_message_ids[fan_id].add(message_id)
        # Evict oldest if over threshold (clear entire fan set as simple LRU)
        total = sum(len(s) for s in self._processed_message_ids.values())
        if total > self._max_dedup_entries:
            # Remove the fan with the most entries
            worst = max(self._processed_message_ids, key=lambda fid: len(self._processed_message_ids[fid]))
            self._processed_message_ids[worst].clear()
