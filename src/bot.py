"""
Fansly AI Bot Orchestrator — Ties all 17 systems to the apifansly.com API.

This is the main chat loop: poll chats → process messages → send replies.
Every message flows through the persona, funnel, script, NLP, reciprocity,
aftercare, and tier systems before a response is generated.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from .fansly_client import FanslyApiClient, ChatInfo, MessageInfo
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
from .messaging.policy import MessageContentPolicy
from .persistence.pipeline import (
    InboundMessageRecord,
    MessageProcessingRepository,
    OUTBOX_PENDING,
    OUTBOX_SENDING,
)

if TYPE_CHECKING:
    from .persistence.state import ConversationStateRepository

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
        state_repo: Optional["ConversationStateRepository"] = None,
    ):
        self.client = client
        self.creator_id = creator_id
        self.account_id = client.account_id

        # Load persona + validator for voice consistency
        self.persona = persona_loader.load(creator_id)
        self.validator = PersonaValidator(self.persona)

        # Track active fan sessions (fan_id -> FanSession)
        self.sessions: dict[str, FanSession] = {}
        self.note_repo = note_repo

        # PPV Sequence System
        self.sequence_repo = SequenceRepository(engine=self.note_repo.engine)

        # Memory: persistent history + LLM fact extraction
        self.message_store = message_store
        self.fact_extractor = fact_extractor
        self.state_repo = state_repo
        self.processing_repo = (
            MessageProcessingRepository(state_repo.engine)
            if state_repo is not None
            else None
        )
        self.content_policy = MessageContentPolicy()
        self._runtime_state_versions: dict[str, int] = {}
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
        if self.processing_repo:
            recovered = self.processing_repo.recover_interrupted(
                self.creator_id
            )
            if any(recovered.values()):
                logger.warning(
                    "Recovered interrupted message work: %s",
                    recovered,
                )

    # ─── MAIN LOOP ──────────────────────────────────────

    def poll_and_process(self, filter_type: str = "all", max_chats: int = 50) -> bool:
        """Main loop: fetch chats, process chats with unread messages, send replies.

        Returns True if any chat had unread messages this cycle, False otherwise —
        the caller uses this to drive idle-adaptive polling.
        """
        if not self.enabled:
            logger.debug("Bot disabled — skipping poll cycle")
            return False

        if self.processing_repo and self.state_repo:
            return self._poll_and_process_durable(
                max_messages=max_chats,
            )

        chats = self.client.get_all_chats(filter_type=filter_type)
        unread_chats = [c for c in chats if c.unread_count > 0]
        logger.info(f"{len(chats)} chats total, {len(unread_chats)} with unread messages")

        for chat in unread_chats[:max_chats]:
            try:
                self._process_chat(chat)
            except Exception as e:
                logger.error(f"Error processing chat {chat.chat_id}: {e}")
            finally:
                self._persist_runtime_state(chat.partner_account_id)

        return len(unread_chats) > 0

    def _poll_and_process_durable(self, *, max_messages: int) -> bool:
        """Ingest changed chats, then drain the durable inbox oldest-first."""
        checkpoint = self.state_repo.get_poll_cursor(
            self.creator_id,
            "changed-chats",
        )
        chats, next_checkpoint = self._fetch_incremental_chats(checkpoint)
        ingested = 0
        scan_complete = True
        for chat in chats:
            try:
                ingested += self._ingest_chat_messages(chat)
            except Exception:
                scan_complete = False
                logger.exception(
                    "Failed to ingest changed chat %s",
                    chat.chat_id,
                )
        if scan_complete and next_checkpoint is not None:
            self.state_repo.set_poll_cursor(
                self.creator_id,
                "changed-chats",
                next_checkpoint,
            )

        processed = 0
        for _ in range(max(0, max_messages)):
            inbound = self.processing_repo.claim_next_inbound(
                self.creator_id
            )
            if inbound is None:
                break
            terminal = self._process_claimed_inbound(inbound)
            processed += 1
            if not terminal:
                break
        return bool(ingested or processed)

    def _fetch_incremental_chats(
        self,
        checkpoint: str | None,
    ) -> tuple[list[ChatInfo], str | None]:
        """Fetch newest pages only until the previous durable chat head."""
        changed: list[ChatInfo] = []
        offset: int | None = 0
        next_checkpoint: str | None = None
        reached_checkpoint = False
        while offset is not None and not reached_checkpoint:
            page, offset = self.client.list_chats_page(
                limit=100,
                offset=offset,
                order="newest",
            )
            if next_checkpoint is None and page:
                next_checkpoint = self._chat_checkpoint(page[0])
            for chat in page:
                current = self._chat_checkpoint(chat)
                if checkpoint is not None and current == checkpoint:
                    reached_checkpoint = True
                    if chat.unread_count <= 0:
                        break
                if (
                    checkpoint is None
                    or chat.unread_count > 0
                    or self.state_repo.conversation_changed(
                        self.creator_id,
                        chat.chat_id,
                        chat.last_message_id,
                    )
                ):
                    changed.append(chat)
                if reached_checkpoint:
                    break
        return changed, next_checkpoint

    @staticmethod
    def _chat_checkpoint(chat: ChatInfo) -> str:
        return json.dumps(
            [chat.chat_id, chat.last_message_id],
            separators=(",", ":"),
        )

    def _ingest_chat_messages(self, chat: ChatInfo) -> int:
        """Fetch unseen messages, sort them, and insert inbound rows once."""
        fan_id = chat.partner_account_id
        self.state_repo.ensure_conversation(
            self.creator_id,
            fan_id,
            chat.chat_id,
            display_name=chat.partner_display_name,
        )
        known_message_id, _ = self.state_repo.get_conversation_checkpoint(
            self.creator_id,
            chat.chat_id,
        )

        # First observation of an already-read chat establishes a baseline;
        # it must not trigger replies to historical messages.
        if known_message_id is None and chat.unread_count <= 0:
            self.state_repo.update_conversation_checkpoint(
                self.creator_id,
                chat.chat_id,
                last_platform_message_id=chat.last_message_id,
            )
            return 0

        unseen: list[MessageInfo] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        found_checkpoint = False
        unread_fan_messages = 0
        while True:
            messages, next_cursor = self.client.list_messages(
                chat.chat_id,
                limit=100,
                cursor=cursor,
            )
            for message in messages:
                if (
                    known_message_id is not None
                    and message.message_id == known_message_id
                ):
                    found_checkpoint = True
                    break
                unseen.append(message)
                if message.is_from_fan:
                    unread_fan_messages += 1
            if found_checkpoint or not next_cursor:
                cursor = next_cursor
                break
            if (
                known_message_id is None
                and unread_fan_messages >= chat.unread_count
            ):
                cursor = next_cursor
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(
                    f"Repeated message cursor for chat {chat.chat_id}"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        unseen.sort(
            key=lambda message: (
                message.created_at,
                message.message_id,
            )
        )
        inbound_messages = [
            message for message in unseen if message.is_from_fan
        ]
        if known_message_id is None:
            inbound_messages = inbound_messages[-chat.unread_count :]

        inserted = 0
        for message in inbound_messages:
            _, created = self.processing_repo.insert_inbound(
                creator_id=self.creator_id,
                platform_message_id=message.message_id,
                fan_id=fan_id,
                chat_id=chat.chat_id,
                content=message.content,
                provider_created_at=self._provider_datetime(
                    message.created_at
                ),
            )
            inserted += int(created)

        newest = max(
            unseen,
            key=lambda message: (
                message.created_at,
                message.message_id,
            ),
            default=None,
        )
        self.state_repo.update_conversation_checkpoint(
            self.creator_id,
            chat.chat_id,
            last_platform_message_id=(
                chat.last_message_id
                or (newest.message_id if newest else known_message_id)
            ),
            provider_cursor=cursor,
            last_activity_at=(
                self._provider_datetime(newest.created_at)
                if newest
                else None
            ),
        )
        return inserted

    @staticmethod
    def _provider_datetime(timestamp: float) -> datetime:
        numeric = float(timestamp or 0)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, timezone.utc)

    @staticmethod
    def _provider_timestamp(value: datetime) -> float:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    def _process_claimed_inbound(
        self,
        inbound: InboundMessageRecord,
    ) -> bool:
        """Process one claimed row and deliver its outbox entry at most once."""
        try:
            outbox = self.processing_repo.get_outbox_for_inbound(inbound.id)
            if outbox is None:
                policy = self.content_policy.validate_inbound(
                    inbound.content
                )
                if not policy.approved:
                    logger.info(
                        "Skipping inbound %s: %s",
                        inbound.platform_message_id,
                        policy.reason,
                    )
                    self.processing_repo.complete_without_response(
                        inbound.id
                    )
                    return True
                chat = ChatInfo(
                    chat_id=inbound.chat_id,
                    partner_account_id=inbound.fan_id,
                    partner_username="",
                    partner_display_name="",
                    unread_count=1,
                    last_message_id=inbound.platform_message_id,
                )
                message = MessageInfo(
                    message_id=inbound.platform_message_id,
                    content=policy.content,
                    sender_id=inbound.fan_id,
                    created_at=self._provider_timestamp(
                        inbound.provider_created_at
                    ),
                    is_from_fan=True,
                )
                approved = self._prepare_message(
                    chat,
                    message,
                    [message],
                )
                self._persist_runtime_state(inbound.fan_id)
                if not approved:
                    self.processing_repo.complete_without_response(
                        inbound.id
                    )
                    return True
                outbox, _ = self.processing_repo.enqueue_outbox(
                    inbound=inbound,
                    content=approved,
                )

            if outbox.status != OUTBOX_PENDING:
                return True
            sending = self.processing_repo.claim_outbox(outbox.id)
            if sending is None:
                return False
            try:
                sent = self.client.send_message(
                    sending.chat_id,
                    sending.content,
                )
                if not sent.success or not sent.message_id:
                    raise RuntimeError(
                        "Provider did not confirm a sent message ID"
                    )
            except Exception as exc:
                self.processing_repo.mark_delivery_unknown(
                    sending.id,
                    str(exc),
                )
                logger.exception(
                    "Delivery outcome unknown for outbox %s",
                    sending.id,
                )
                return True

            self.processing_repo.complete_delivery(
                sending.id,
                sent.message_id,
            )
            self._record_sent_reply(
                sending.fan_id,
                sending.content,
                sent.message_id,
            )
            self._persist_runtime_state(sending.fan_id)
            return True
        except Exception as exc:
            current = self.processing_repo.get_outbox_for_inbound(
                inbound.id
            )
            if current is None or current.status == OUTBOX_PENDING:
                self.processing_repo.release_inbound(
                    inbound.id,
                    str(exc),
                )
                terminal = False
            elif current.status == OUTBOX_SENDING:
                self.processing_repo.mark_delivery_unknown(
                    current.id,
                    str(exc),
                )
                terminal = True
            else:
                terminal = True
            logger.exception(
                "Failed to process inbound %s",
                inbound.platform_message_id,
            )
            return terminal

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
        """Compatibility path for tests/dev without the durable repository."""
        messages, _ = self.client.list_messages(chat.chat_id, limit=10)
        inbound = sorted(
            (message for message in messages if message.is_from_fan),
            key=lambda message: (
                message.created_at,
                message.message_id,
            ),
        )
        for message in inbound:
            if self._has_processed(
                chat.partner_account_id,
                message.message_id,
            ):
                continue
            approved = self._prepare_message(chat, message, messages)
            if approved:
                sent = self.client.send_message(
                    chat.chat_id,
                    approved,
                )
                if not sent.success or not sent.message_id:
                    raise RuntimeError(
                        "Provider did not confirm a sent message ID"
                    )
                self._record_sent_reply(
                    chat.partner_account_id,
                    approved,
                    sent.message_id,
                )
            self._mark_processed(
                chat.partner_account_id,
                message.message_id,
                chat.chat_id,
            )

    def _prepare_message(
        self,
        chat: ChatInfo,
        latest: MessageInfo,
        messages: list[MessageInfo] | None = None,
    ) -> str | None:
        """Load persistent state and produce one policy-approved response."""
        fan_id = chat.partner_account_id
        messages = messages or [latest]

        if self.state_repo:
            self.state_repo.ensure_conversation(
                self.creator_id,
                fan_id,
                chat.chat_id,
                display_name=chat.partner_display_name,
            )

        # Get or create fan session
        if fan_id not in self.sessions:
            if self.state_repo:
                session, durable_state = self.state_repo.load_session(
                    self.creator_id,
                    fan_id,
                )
                self.sessions[fan_id] = session
                self._runtime_state_versions[fan_id] = durable_state.version
                self._extract_counters[fan_id] = durable_state.extract_counter
                self._purchase_count_cache[fan_id] = (
                    durable_state.purchase_count_seen
                )
                self.rhythm_engines[fan_id] = self.state_repo.restore_rhythm(
                    durable_state
                )
            else:
                self.sessions[fan_id] = FanSession(
                    fan_id=fan_id, creator_id=self.creator_id
                )

        # Get fan notes
        note = self.note_repo.get(fan_id, self.creator_id)
        if note is None:
            note = FanNote(fan_id=fan_id, creator_id=self.creator_id)

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
            reply = self._prepare_aftercare(fan_id)
        else:
            # 2. Check churn risk
            risk = self.churn_predictor.calculate_risk(
                days_since_last_purchase=self._days_since_last_purchase(note),
                days_since_last_message=0,  # they just messaged
                sentiment_score=0.5,  # neutral default
            )
            if risk > 0.6:
                reply = self._prepare_reengagement(fan_id, risk)
            elif self.reciprocity.is_premium_ready(fan_id):
                # Phase 6 will attach a typed PPV payload to this same outbox.
                # Until then, only the approved text offer is delivered.
                reply = self._prepare_premium_offer(fan_id, note)
            else:
                # 4. Generate contextual reply based on funnel stage
                reply = self._generate_reply(
                    chat.chat_id, fan_id, latest, session, note
                )

        if reply:
            # Repair explicit persona phrases before final policy validation.
            validation = self.validator.validate(reply)
            if not validation.passed:
                logger.warning(
                    f"Persona violation for {fan_id}: {validation.violations}"
                )
                # Fix: strip forbidden phrases
                for phrase in self.persona.forbidden_phrases:
                    reply = reply.replace(phrase, self.persona.pet_names[0] if self.persona.pet_names else "babe")
            return self._style_and_approve(fan_id, reply)
        return None

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
            # Select the next offer. Phase 6 will attach PPV media/price as a
            # typed outbox payload; Phase 5 keeps every send on the text
            # outbox instead of bypassing it with direct provider calls.
            if funnel.can_send_ppv():
                result = self.sequence_engine.get_next_ppv(fan_id, "offer", fan_total_spent=note.total_spent if note else 0)
                if result:
                    _, step = result
                    return (
                        step.offer_script
                        or step.tease_script
                        or self.variation.pick("push")
                    )

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

    def _style_and_approve(self, fan_id: str, text: str) -> str | None:
        """Humanize, style, and apply the final persona/content gates."""
        profile = self._profile_for(fan_id)
        humanized = self.humanizer.humanize(text)
        styled = self.style_mirror.adapt(
            humanized if humanized else text,
            profile,
            common_typos=self.persona.common_typos,
            pet_names=self.persona.pet_names,
        )
        policy = self.content_policy.validate_outbound(styled)
        if not policy.approved:
            logger.warning(
                "Outbound response rejected for %s: %s",
                fan_id,
                policy.reason,
            )
            return None
        validation = self.validator.validate(policy.content)
        if not validation.passed:
            logger.warning(
                "Styled response rejected for %s: %s",
                fan_id,
                validation.violations,
            )
            return None
        return policy.content

    def _record_sent_reply(
        self,
        fan_id: str,
        content: str,
        provider_message_id: str | None = None,
    ) -> None:
        session = self.sessions.get(fan_id)
        if session:
            session.add_message("creator", content)
        if self.message_store:
            try:
                self.message_store.save_message(
                    fan_id,
                    self.creator_id,
                    "creator",
                    content,
                    provider_message_id,
                )
            except Exception as e:
                logger.error(f"Failed to persist styled reply: {e}")
        logger.info("Replied to %s: %s...", fan_id, content[:50])

    def _styled_send(self, chat_id: str, fan_id: str, text: str) -> str:
        """Compatibility helper; production delivery uses the durable outbox."""
        approved = self._style_and_approve(fan_id, text)
        if not approved:
            return ""
        sent = self.client.send_message(chat_id, approved)
        if not sent.success or not sent.message_id:
            raise RuntimeError("Provider did not confirm a sent message ID")
        self._record_sent_reply(fan_id, approved, sent.message_id)
        return approved

    def _generate_push_message(self, note: Optional[FanNote]) -> str:
        """Generate a flirtatious push spike, personalized with remembered facts."""
        if note and note.facts:
            # Reference the most recently learned fact — shows we remembered
            fact = note.facts[-1]
            return f"I was just thinking about you... especially after what you told me about {fact} 😏"
        if note and note.preferences:
            return self.variation.pick("push")
        return self.variation.pick("push")

    def _prepare_aftercare(self, fan_id: str) -> str | None:
        """Prepare aftercare, then loop the durable funnel to rapport."""
        plan = self.aftercare.trigger_aftercare(50.0, fan_id)  # TODO: get actual amount
        response = (
            self.variation.pick("aftercare")
            if "thanks" in plan.actions
            else None
        )
        self.aftercare.mark_aftercare_sent(fan_id)
        # Complete the spiral: AFTERCARE → RAPPORT at next escalation level
        sess = self.sessions.get(fan_id)
        if sess:
            try:
                sess.funnel.complete_aftercare()
                logger.info(f"Spiral: aftercare complete for {fan_id}, back to RAPPORT at level {sess.funnel.level.number}")
            except Exception:
                pass
        return response

    def _prepare_reengagement(self, fan_id: str, risk: float) -> str | None:
        """Prepare one re-engagement response."""
        intervention = self.churn_predictor.get_intervention(risk)
        if intervention == "reengage_soft":
            response = self.variation.pick("reengage_soft")
        elif intervention in ("reengage_hard", "win_back"):
            response = self.variation.pick("reengage_hard")
        else:
            response = None
        self.churn_predictor.mark_reengaged(fan_id)
        return response

    def _prepare_premium_offer(
        self,
        fan_id: str,
        note: FanNote,
    ) -> str:
        """Prepare premium offer text without bypassing the outbox."""
        result = self.sequence_engine.get_next_ppv(fan_id, "offer", fan_total_spent=note.total_spent if note else 0)
        if result:
            _, step = result
            if step.price >= 25 or step.offer_script:
                self.reciprocity.mark_premium_pitched(fan_id)
                return (
                    step.offer_script
                    or step.tease_script
                    or self.variation.pick("premium_ppv")
                )
        self.reciprocity.mark_premium_pitched(fan_id)
        return self.variation.pick("premium_ppv")

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
        if self.state_repo:
            return self.state_repo.has_processed(
                self.creator_id,
                message_id,
            )
        return fan_id in self._processed_message_ids and message_id in self._processed_message_ids[fan_id]

    def _mark_processed(
        self,
        fan_id: str,
        message_id: str,
        chat_id: str | None = None,
    ):
        """Mark a message as processed. LRU eviction at max_dedup_entries."""
        if self.state_repo:
            self.state_repo.mark_processed(
                self.creator_id,
                message_id,
                fan_id,
                chat_id,
            )
            return
        if fan_id not in self._processed_message_ids:
            self._processed_message_ids[fan_id] = set()
        self._processed_message_ids[fan_id].add(message_id)
        # Evict oldest if over threshold (clear entire fan set as simple LRU)
        total = sum(len(s) for s in self._processed_message_ids.values())
        if total > self._max_dedup_entries:
            # Remove the fan with the most entries
            worst = max(self._processed_message_ids, key=lambda fid: len(self._processed_message_ids[fid]))
            self._processed_message_ids[worst].clear()

    def _persist_runtime_state(self, fan_id: str):
        if not self.state_repo:
            return
        session = self.sessions.get(fan_id)
        if session is None:
            return
        try:
            rhythm = self.rhythm_engines.get(fan_id)
            state = self.state_repo.capture_session(
                session,
                extract_counter=self._extract_counters.get(fan_id, 0),
                purchase_count_seen=self._purchase_count_cache.get(fan_id, 0),
                rhythm=rhythm,
                version=self._runtime_state_versions.get(fan_id, 1),
            )
            saved = self.state_repo.save_state(state)
            self._runtime_state_versions[fan_id] = saved.version
        except Exception as e:
            logger.error(
                f"Failed to persist runtime state for {fan_id}: {e}",
                exc_info=True,
            )
