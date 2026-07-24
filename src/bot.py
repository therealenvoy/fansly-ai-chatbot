"""
Fansly AI Bot Orchestrator — Ties all 17 systems to the apifansly.com API.

This is the main chat loop: poll chats → process messages → send replies.
Every message flows through the persona, funnel, script, NLP, reciprocity,
aftercare, and tier systems before a response is generated.
"""

import logging
from typing import Optional

from .fansly_client import FanslyClient, FanslyConfig, ChatInfo, MessageInfo
from .persona.loader import PersonaLoader
from .persona.validator import PersonaValidator
from .funnel.state_machine import FunnelStateMachine, FunnelStage
from .funnel.session import FanSession
from .notes.repository import FanNoteRepository
from .notes.models import FanNote
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

logger = logging.getLogger(__name__)


class FanslyBot:
    """Main orchestrator for the Fansly AI chatbot."""

    def __init__(
        self,
        client: FanslyClient,
        persona_loader: PersonaLoader,
        note_repo: FanNoteRepository,
        creator_id: str = "sunny_charm",
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

    # ─── MAIN LOOP ──────────────────────────────────────

    def poll_and_process(self, filter_type: str = "all", max_chats: int = 50):
        """Main loop: fetch chats, process unread messages, send replies."""
        chats = self.client.get_all_chats(filter_type=filter_type)
        logger.info(f"Processing {len(chats)} chats")

        for chat in chats[:max_chats]:
            try:
                self._process_chat(chat)
            except Exception as e:
                logger.error(f"Error processing chat {chat.chat_id}: {e}")

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
        session = self.sessions[fan_id]
        session.add_message("subscriber", latest.content)

        # ─── DECISION PIPELINE ───────────────────────────

        # 1. Check if we're in aftercare mode
        if self.aftercare.is_aftercare_due(fan_id):
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

            self.client.send_message(chat.chat_id, reply)
            session.add_message("creator", reply)
            logger.info(f"Replied to {fan_id}: {reply[:50]}...")

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
            "rapport_count": funnel.stage_history.count(FunnelStage.RAPPORT),
            "purchase_count": note.purchase_count if note else 0,
            "total_spent": note.total_spent if note else 0,
        }

        # Get push-pull engine for this fan
        if fan_id not in self.rhythm_engines:
            self.rhythm_engines[fan_id] = PushPullEngine()
        rhythm = self.rhythm_engines[fan_id]

        # Analyze fan message for push-pull signals
        analysis = rhythm.analyze_fan_message(message.content)

        # ─── Stage-based routing ─────────────────────────

        if funnel.current_stage == FunnelStage.RAPPORT:
            if funnel.min_messages_before_tease() == 0 and analysis.ready_for_tease:
                # Fan is ready — move to tease stage
                funnel.transition(FunnelStage.TEASE)
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
            return f"Hey {note.display_name or self.persona.pet_names[0] if note and note.display_name else 'babe'}! How's your day going? 💕"

        elif funnel.current_stage == FunnelStage.TEASE:
            # Check if fan is ready for offer
            if analysis.ready_for_tease:
                funnel.transition(FunnelStage.OFFER)
                scripts = self.script_library.get_by_category(ScriptCategory.PPV_SOFT_TEASE)
                if scripts and len(scripts[0].messages) > 1:
                    return self.script_engine.resolve(scripts[0], context)[1]

            return self._generate_push_message(note)

        elif funnel.current_stage == FunnelStage.OFFER:
            # Send PPV offer — check if we can send actual PPV
            if funnel.can_send_ppv():
                # TODO: Integrate with vault media for actual PPV sending
                scripts = self.script_library.get_by_category(ScriptCategory.PPV_SOFT_TEASE)
                if scripts and len(scripts[0].messages) > 2:
                    return self.script_engine.resolve(scripts[0], context)[2]

        elif funnel.current_stage == FunnelStage.HANDLE:
            # Classify objection and route
            objection_type = self.objections.classify_objection(message.content)
            handler_name = self.objections.get_handler(objection_type)
            script = self.script_library.get(handler_name)
            if script:
                return self.script_engine.resolve(script, context)[0]

        elif funnel.current_stage == FunnelStage.CLOSE:
            return "I'm so glad you enjoyed it 😘"

        # Fallback
        return self._generate_push_message(note)

    # ─── HELPERS ────────────────────────────────────────

    def _generate_push_message(self, note: Optional[FanNote]) -> str:
        """Generate a flirtatious push spike."""
        if note and note.preferences:
            pref = note.preferences[0]
            return f"I was just thinking about you... especially that thing you like 😏"
        return "I was just thinking about you... wish you were here right now 😏"

    def _send_aftercare(self, chat_id: str, fan_id: str):
        """Send aftercare sequence after a purchase."""
        plan = self.aftercare.trigger_aftercare(50.0, fan_id)  # TODO: get actual amount
        if "thanks" in plan.actions:
            self.client.send_message(chat_id, "That was so fun... I don't do that with everyone, you know 😘")
        self.aftercare.mark_aftercare_sent(fan_id)

    def _send_reengagement(self, chat_id: str, fan_id: str, risk: float):
        """Send re-engagement message for at-risk fans."""
        intervention = self.churn_predictor.get_intervention(risk)
        if intervention == "reengage_soft":
            self.client.send_message(chat_id, "Hey... I haven't heard from you in a bit. Missing our chats 💕")
        elif intervention in ("reengage_hard", "win_back"):
            self.client.send_message(chat_id, "I made something new and thought of you first... want to see? 😏")
        self.churn_predictor.mark_reengaged(fan_id)

    def _send_premium_ppv(self, chat_id: str, fan_id: str, note: FanNote):
        """Send premium PPV offer when reciprocity debt is ready."""
        base_price = 25.0
        premium = self.reciprocity.suggest_premium_price(fan_id, base_price)
        # TODO: Attach actual vault media
        self.client.send_message(
            chat_id,
            f"Since you're my absolute favorite... I made something extra special. Want to see? 😘",
        )
        self.reciprocity.mark_premium_pitched(fan_id)

    def _days_since_last_purchase(self, note: Optional[FanNote]) -> int:
        if not note or not note.last_purchase_at:
            return 90  # default: treat as lapsed
        from datetime import datetime, timezone
        delta = datetime.now(timezone.utc) - note.last_purchase_at
        return delta.days

    def _has_classified(self, fan_id: str) -> bool:
        note = self.note_repo.get(fan_id, self.creator_id)
        return note is not None and note.relationship_stage.startswith("classified_")
