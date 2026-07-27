"""
Provider-neutral Fansly AI Bot orchestrator.

This is the main chat loop: poll chats → process messages → send replies.
Every message flows through the persona, funnel, script, NLP, reciprocity,
aftercare, and tier systems before a response is generated.
"""

import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

from .fansly_client import FanslyApiClient, ChatInfo, MessageInfo
from .conversation.llm import DeepSeekChatResponder
from .conversation.brain import ConversationDecision
from .conversation.mode import BotMode, ConversationPolicy
from .conversation.repository import ConversationDecisionRepository
from .conversation.brain2 import ConversationQualityGate
from .conversation.brain2_repository import (
    ConversationEpisodeRepository,
    ConversationOutcomeRepository,
    FanConversationStateRepository,
    FanMemoryV2Repository,
)
from .conversation.brain2_memory_async import MemoryExtractionService
from .conversation.brain2_memory import (
    ExtractedMemoryWriter,
    LegacyMemoryBackfill,
)
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
from .scripts.repository import ScriptTemplateRepository
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
from .humanize.filter import HumanizerFilter
from .humanize.variation import VariationPool
from .messaging.models import OutboundKind, OutboundMessage
from .messaging.policy import MessageContentPolicy
from .persistence.pipeline import (
    InboundMessageRecord,
    MessageProcessingRepository,
    OutboxMessageRecord,
    OUTBOX_PENDING,
    OUTBOX_SENDING,
)
from .persistence.purchases import PurchaseRepository
from .persistence.presence import PresenceRepository

if TYPE_CHECKING:
    from .persistence.state import ConversationStateRepository
    from .settings.chat_guidance import ChatGuidanceService
    from .webhooks.onlyfansapi import OnlyFansApiFanslyMessage

logger = logging.getLogger(__name__)


class LaunchGuardError(RuntimeError):
    """Raised when an operator tries to enable an unsafe pilot launch."""


class FanslyBot:
    """Main orchestrator for the Fansly AI chatbot."""

    def __init__(
        self,
        client: FanslyApiClient,
        persona_loader: PersonaLoader,
        note_repo: FanNoteRepository,
        state_repo: "ConversationStateRepository",
        creator_id: str = "sunny_charm",
        message_store: Optional[MessageStore] = None,
        fact_extractor: Optional[LLMFactExtractor] = None,
        allowed_fan_ids: Optional[set[str]] = None,
        require_fan_allowlist: bool = False,
        bot_mode: BotMode | str = BotMode.FULL_PPV,
        chat_responder: DeepSeekChatResponder | None = None,
        shadow_brain_service=None,
        brain_settings_service=None,
        episode_service=None,
        memory_extraction_service=None,
        chat_guidance: "ChatGuidanceService | None" = None,
        enable_unread_replies: bool = True,
        enable_online_outreach: bool = False,
        enable_stalled_outreach: bool = False,
        outreach_existing_online: bool = False,
        online_window_seconds: int = 600,
        proactive_cooldown_hours: int = 48,
        max_proactive_per_hour: int = 3,
        max_proactive_per_day: int = 15,
        max_proactive_per_fan_per_day: int = 1,
        presence_batch_size: int = 100,
        presence_poll_interval_seconds: int = 300,
        stalled_after_hours: int = 24,
        stalled_scan_interval_seconds: int = 300,
        stalled_scan_batch_size: int = 5000,
        reply_delay_min_seconds: int = 0,
        reply_delay_max_seconds: int = 0,
        processing_retry_base_seconds: int = 5,
        processing_retry_max_seconds: int = 60,
    ):
        self.client = client
        self.persona_loader = persona_loader
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
        if self.state_repo is None:
            raise ValueError(
                "state_repo is required; all message processing must use "
                "the durable inbox/outbox"
            )
        self.allowed_fan_ids = frozenset(
            str(fan_id).strip()
            for fan_id in (allowed_fan_ids or set())
            if str(fan_id).strip()
        )
        self.require_fan_allowlist = bool(require_fan_allowlist)
        self.bot_mode = BotMode.parse(bot_mode)
        self.chat_responder = chat_responder
        self.shadow_brain_service = shadow_brain_service
        self.brain_settings_service = brain_settings_service
        self.episode_service = episode_service
        self.chat_guidance = chat_guidance
        self.enable_unread_replies = bool(enable_unread_replies)
        self.enable_online_outreach = bool(enable_online_outreach)
        self.enable_stalled_outreach = bool(enable_stalled_outreach)
        self.outreach_existing_online = bool(outreach_existing_online)
        self.online_window_seconds = max(60, int(online_window_seconds))
        self.proactive_cooldown_hours = max(
            1, int(proactive_cooldown_hours)
        )
        self.max_proactive_per_hour = max(
            0, int(max_proactive_per_hour)
        )
        self.max_proactive_per_day = max(
            0, int(max_proactive_per_day)
        )
        self.max_proactive_per_fan_per_day = max(
            0, int(max_proactive_per_fan_per_day)
        )
        self.presence_batch_size = min(
            max(1, int(presence_batch_size)),
            100,
        )
        self.presence_poll_interval_seconds = max(
            0,
            int(presence_poll_interval_seconds),
        )
        self.stalled_after_hours = max(1, int(stalled_after_hours))
        self.stalled_scan_interval_seconds = max(
            0,
            int(stalled_scan_interval_seconds),
        )
        self.stalled_scan_batch_size = min(
            max(1, int(stalled_scan_batch_size)),
            5000,
        )
        self.reply_delay_min_seconds = max(
            0,
            int(reply_delay_min_seconds),
        )
        self.reply_delay_max_seconds = max(
            self.reply_delay_min_seconds,
            int(reply_delay_max_seconds),
        )
        self.processing_retry_base_seconds = max(
            0,
            int(processing_retry_base_seconds),
        )
        self.processing_retry_max_seconds = max(
            self.processing_retry_base_seconds,
            int(processing_retry_max_seconds),
        )
        self._presence_offset = 0
        self._last_presence_poll_at: datetime | None = None
        self._last_stalled_scan_at: datetime | None = None
        self.processing_repo = MessageProcessingRepository(
            self.state_repo.engine
        )
        self.purchase_repo = PurchaseRepository(self.state_repo.engine)
        self.presence_repo = PresenceRepository(self.state_repo.engine)
        self.conversation_decision_repo = ConversationDecisionRepository(
            self.state_repo.engine
        )
        self.conversation_outcome_repo = ConversationOutcomeRepository(
            self.state_repo.engine
        )
        self.brain_state_repo = FanConversationStateRepository(
            self.state_repo.engine
        )
        self.memory_v2_repo = FanMemoryV2Repository(self.state_repo.engine)
        self.episode_repo = ConversationEpisodeRepository(self.state_repo.engine)
        self.memory_v2_backfill = LegacyMemoryBackfill(self.memory_v2_repo)
        self.extracted_memory_writer = ExtractedMemoryWriter(
            self.memory_v2_repo
        )
        self.note_extractor = NoteExtractor(llm_client=None)  # merge() only
        self.memory_extraction_service = memory_extraction_service
        if (
            self.memory_extraction_service is None
            and self.fact_extractor is not None
            and self.fact_extractor.enabled
        ):
            self.memory_extraction_service = MemoryExtractionService(
                fact_extractor=self.fact_extractor,
                memory_writer=self.extracted_memory_writer,
                note_repository=self.note_repo,
                note_extractor=self.note_extractor,
            )
        self.brain_quality_gate = ConversationQualityGate()
        self.content_policy = MessageContentPolicy()
        self.conversation_policy = ConversationPolicy()
        self._runtime_state_versions: dict[str, int] = {}
        self._extract_counters: dict[str, int] = {}

        # 17-system components
        self.classifier = FanClassifier()
        self.rhythm_engines: dict[str, PushPullEngine] = {}
        self.script_repo = ScriptTemplateRepository(
            self.state_repo.engine,
            creator_id,
        )
        self.script_library = ScriptLibrary()
        self.reload_scripts()
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

        recovered = self.processing_repo.recover_interrupted(
            self.creator_id
        )
        if any(recovered.values()):
            logger.warning(
                "Recovered interrupted message work: %s",
                recovered,
            )
        if self.bot_mode == BotMode.CONVERSATION:
            quarantined = self.processing_repo.block_pending_non_text(
                self.creator_id,
                "conversation mode permits text messages only",
            )
            if quarantined:
                logger.warning(
                    "Quarantined %s pending non-text outbox message(s)",
                    quarantined,
                )

    # ─── MAIN LOOP ──────────────────────────────────────

    def reload_persona(self) -> None:
        """Reload and atomically replace the active creator persona."""
        persona = self.persona_loader.load(self.creator_id)
        validator = PersonaValidator(persona)
        self.persona = persona
        self.validator = validator

    def reload_scripts(self) -> None:
        """Reload built-ins plus active creator-owned script overrides."""
        self.script_library.load_builtin()
        self.script_library.apply_overrides(
            [
                stored.template
                for stored in self.script_repo.list_scripts(
                    active_only=True
                )
            ]
        )

    @staticmethod
    def _fan_memory(note: FanNote | None) -> list[str]:
        """Render compact, durable fan context without dumping full history."""
        if note is None:
            return []
        memory: list[str] = []
        if note.relationship_stage and note.relationship_stage != "new":
            memory.append(
                f"Relationship stage: {note.relationship_stage}"
            )
        if note.occupation:
            memory.append(f"Occupation: {note.occupation}")
        memory.extend(
            f"Preference: {item}"
            for item in note.preferences
            if str(item).strip()
        )
        memory.extend(
            f"Emotional cue: {item}"
            for item in note.emotional_triggers
            if str(item).strip()
        )
        memory.extend(
            f"Hard limit: {item}"
            for item in note.hard_limits
            if str(item).strip()
        )
        memory.extend(
            f"Known fact: {item}"
            for item in note.facts
            if str(item).strip()
        )
        if note.notes.strip():
            memory.append(f"Operator note: {note.notes.strip()}")
        return memory

    def _backfill_memory_v2(self, note: FanNote | None) -> None:
        if note is None:
            return
        try:
            self.memory_v2_backfill.run(note)
        except Exception:
            logger.exception(
                "Legacy Memory V2 backfill failed for %s",
                note.fan_id,
            )

    def poll_and_process(
        self,
        filter_type: str = "all",
        max_chats: int = 50,
        *,
        reconcile: bool = True,
        outreach: bool = True,
    ) -> bool:
        """Main loop: fetch chats, process chats with unread messages, send replies.

        Returns True if any chat had unread messages this cycle, False otherwise —
        the caller uses this to drive idle-adaptive polling.
        """
        if not self.enabled:
            if outreach and self.enable_online_outreach:
                try:
                    self._poll_presence(queue_outreach=False)
                except Exception:
                    logger.exception(
                        "Presence observation failed while bot is disabled"
                    )
            logger.debug("Bot disabled — skipping send cycle")
            return False

        return self._poll_and_process_durable(
            max_messages=max_chats,
            reconcile=reconcile,
            outreach=outreach,
        )

    def _poll_and_process_durable(
        self,
        *,
        max_messages: int,
        reconcile: bool = True,
        outreach: bool = True,
    ) -> bool:
        """Ingest changed chats, then drain the durable inbox oldest-first."""
        ledger_updates = 0
        ingested = 0
        if reconcile:
            ledger_updates, ingested = self.reconcile_provider()
        presence_activity = (
            self.poll_presence_outreach() if outreach else False
        )
        stalled_activity = (
            self.poll_stalled_outreach() if outreach else False
        )
        processed = self.drain_pending(max_messages=max_messages)
        return bool(
            ledger_updates
            or ingested
            or processed
            or presence_activity
            or stalled_activity
        )

    def reconcile_provider(self) -> tuple[int, int]:
        """Ingest provider changes without running AI generation or sends."""
        ledger_updates = (
            0
            if self.bot_mode == BotMode.CONVERSATION
            else self._sync_wallet_transactions()
        )
        cursor_scope = self._chat_cursor_scope()
        checkpoint = self.state_repo.get_poll_cursor(
            self.creator_id,
            cursor_scope,
        )
        chats, next_checkpoint = (
            self._fetch_incremental_chats(checkpoint)
            if self.enable_unread_replies
            else ([], checkpoint)
        )
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
                cursor_scope,
                next_checkpoint,
            )

        return ledger_updates, ingested

    def poll_presence_outreach(self) -> bool:
        if not self.enable_online_outreach:
            return False
        try:
            return bool(self._poll_presence())
        except Exception:
            logger.exception(
                "Presence polling failed; unread work will continue"
            )
            return False

    def poll_stalled_outreach(self) -> bool:
        if not self.enable_stalled_outreach:
            return False
        try:
            return bool(self._poll_stalled_conversations())
        except Exception:
            logger.exception(
                "Stalled conversation scan failed; unread work will continue"
            )
            return False

    def drain_pending(self, *, max_messages: int) -> int:
        """Claim and process ready work without polling the provider."""
        processed = 0
        for _ in range(max(0, max_messages)):
            inbound = self.processing_repo.claim_next_inbound(
                self.creator_id,
                allowed_fan_ids=(
                    set(self.allowed_fan_ids)
                    if self.require_fan_allowlist
                    else None
                ),
            )
            if inbound is None:
                break
            terminal = self._process_claimed_inbound(inbound)
            processed += 1
            if not terminal:
                break
        return processed

    def ingest_webhook_message(
        self,
        event: "OnlyFansApiFanslyMessage",
    ) -> bool:
        """Persist one signed provider event and enqueue it idempotently."""
        if not self._fan_allowed(event.fan_id):
            return False
        self.state_repo.ensure_conversation(
            self.creator_id,
            event.fan_id,
            event.chat_id,
            display_name=event.display_name,
            username=event.username,
        )
        if self.message_store is not None:
            self.message_store.save_message(
                event.fan_id,
                self.creator_id,
                "fan",
                event.content,
                event.platform_message_id,
                chat_id=event.chat_id,
                attachments=list(event.attachments),
                created_at=event.provider_created_at,
            )
        inbound_record, created = self.processing_repo.insert_inbound(
            creator_id=self.creator_id,
            platform_message_id=event.platform_message_id,
            fan_id=event.fan_id,
            chat_id=event.chat_id,
            content=event.content,
            provider_created_at=event.provider_created_at,
            trigger_kind="unread",
            available_at=self._reply_available_at(
                event.platform_message_id
            ),
        )
        if created:
            self._attribute_inbound_outcome(
                inbound_record,
                event.provider_created_at,
            )
        return created

    def _attribute_inbound_outcome(
        self,
        inbound: InboundMessageRecord,
        received_at: datetime,
    ) -> None:
        try:
            meaningful = sum(
                character.isalnum() for character in inbound.content
            ) >= 3
            lowered = inbound.content.casefold()
            negative_signal = any(
                marker in lowered
                for marker in (
                    "stop messaging",
                    "don't message",
                    "do not message",
                    "leave me alone",
                    "no more",
                    "unsubscribe",
                )
            )
            window_hours = 24
            if self.brain_settings_service is not None:
                window_hours = int(
                    self.brain_settings_service.snapshot().outcome_window_hours
                )
            self.conversation_outcome_repo.close_expired(
                creator_id=self.creator_id,
                now=received_at,
                window_hours=window_hours,
            )
            self.conversation_outcome_repo.attribute_inbound_reply(
                creator_id=self.creator_id,
                fan_id=inbound.fan_id,
                inbound_message_id=inbound.id,
                received_at=received_at,
                meaningful=meaningful,
                negative_signal=negative_signal,
            )
        except Exception:
            logger.exception(
                "Failed to attribute inbound conversation outcome %s",
                inbound.id,
            )

    def _reply_available_at(self, platform_message_id: str) -> datetime:
        delay_range = (
            self.reply_delay_max_seconds
            - self.reply_delay_min_seconds
        )
        delay = self.reply_delay_min_seconds
        if delay_range > 0:
            digest = hashlib.sha256(
                str(platform_message_id).encode("utf-8")
            ).digest()
            delay += int.from_bytes(digest[:4], "big") % (
                delay_range + 1
            )
        return datetime.now(timezone.utc) + timedelta(seconds=delay)

    def _chat_cursor_scope(self) -> str:
        if not self.require_fan_allowlist:
            return "changed-chats"
        fingerprint = hashlib.sha256(
            "\0".join(sorted(self.allowed_fan_ids)).encode("utf-8")
        ).hexdigest()[:16]
        return f"changed-chats:pilot:{fingerprint}"

    def _fan_allowed(self, fan_id: str) -> bool:
        if not self.require_fan_allowlist:
            return True
        return str(fan_id) in self.allowed_fan_ids

    @property
    def launch_ready(self) -> bool:
        if (
            self.require_fan_allowlist
            and not self.allowed_fan_ids
        ):
            return False
        if self.bot_mode == BotMode.CONVERSATION:
            if not bool(
                self.chat_responder
                and self.chat_responder.enabled
            ):
                return False
            if (
                self.enable_online_outreach
                and self.client.capabilities.supports_user_presence is not True
            ):
                return False
            return bool(
                self.enable_unread_replies
                or self.enable_online_outreach
                or self.enable_stalled_outreach
            )
        capabilities = self.client.capabilities
        return (
            capabilities.supports_paid_messages is True
            and capabilities.supports_vault_albums is True
            and capabilities.supports_attributed_purchases is True
        )

    @property
    def launch_block_reason(self) -> str | None:
        if (
            self.require_fan_allowlist
            and not self.allowed_fan_ids
        ):
            return "controlled launch requires at least one FAN_ALLOWLIST entry"
        if self.bot_mode == BotMode.CONVERSATION:
            if not bool(
                self.chat_responder
                and self.chat_responder.enabled
            ):
                return (
                    "conversation mode requires DEEPSEEK_API_KEY for "
                    "contextual replies"
                )
            if (
                self.enable_online_outreach
                and self.client.capabilities.supports_user_presence is not True
            ):
                return (
                    "configured provider cannot observe recent fan activity"
                )
            if not (
                self.enable_unread_replies
                or self.enable_online_outreach
                or self.enable_stalled_outreach
            ):
                return "conversation mode has no enabled conversation triggers"
            return None
        capabilities = self.client.capabilities
        if capabilities.supports_paid_messages is not True:
            return (
                "configured provider cannot send automated paid PPV messages"
            )
        if capabilities.supports_vault_albums is not True:
            return (
                "configured provider cannot browse Fansly vault albums"
            )
        if capabilities.supports_attributed_purchases is not True:
            return (
                "APIFANSLY_WEBHOOK_TOKEN must be at least 32 characters "
                "for automatic PPV purchase handling"
            )
        return None

    def record_provider_ppv_purchase(
        self,
        *,
        provider_purchase_id: str,
        provider_purchase_ref: str,
        fan_id: str,
        amount_millis: int,
        provider_created_at: datetime,
    ):
        """Apply one exact provider PPV purchase without human review."""
        event, created = self.purchase_repo.record_attributed_purchase(
            creator_id=self.creator_id,
            provider_purchase_id=provider_purchase_id,
            provider_purchase_ref=provider_purchase_ref,
            fan_id=fan_id,
            amount_millis=amount_millis,
            source="provider_webhook",
            provider_created_at=provider_created_at,
        )
        if created:
            self.aftercare.trigger_aftercare(
                purchase_amount=amount_millis / 1000,
                fan_id=fan_id,
            )
        return event, created

    def _sync_wallet_transactions(self) -> int:
        """Persist provider revenue without assigning it to a fan."""
        capabilities = self.client.capabilities
        if capabilities.supports_wallet_transactions is not True:
            return 0
        checkpoint = self.state_repo.get_poll_cursor(
            self.creator_id,
            "wallet-head",
        )
        offset: int | None = 0
        new_head: str | None = None
        rows = []
        reached_checkpoint = False
        try:
            while offset is not None and not reached_checkpoint:
                page, offset = self.client.list_wallet_transactions_page(
                    limit=100,
                    offset=offset,
                )
                if new_head is None and page:
                    new_head = page[0].transaction_id
                for transaction in page:
                    if transaction.transaction_id == checkpoint:
                        reached_checkpoint = True
                        break
                    rows.append(transaction)
                if checkpoint is None:
                    # Establish a bounded initial baseline. Historical wallet
                    # backfill is an explicit operational job, not a surprise
                    # cost inside the chat polling loop.
                    break
            stored = self.purchase_repo.ingest_wallet_transactions(
                self.creator_id,
                rows,
            )
            if new_head is not None:
                self.state_repo.set_poll_cursor(
                    self.creator_id,
                    "wallet-head",
                    new_head,
                )
            return stored
        except Exception:
            logger.exception("Failed to synchronize provider wallet ledger")
            return 0

    def _poll_presence(self, *, queue_outreach: bool = True) -> bool:
        """Observe one bounded fan batch and queue eligible online transitions."""
        if (
            self.bot_mode != BotMode.CONVERSATION
            or not self.enable_online_outreach
        ):
            return False
        if self.client.capabilities.supports_user_presence is not True:
            return False
        now = datetime.now(timezone.utc)
        if (
            self._last_presence_poll_at is not None
            and (
                now - self._last_presence_poll_at
            ).total_seconds() < self.presence_poll_interval_seconds
        ):
            return False
        self._last_presence_poll_at = now
        candidates = self.presence_repo.candidates(
            self.creator_id,
            allowed_fan_ids=(
                set(self.allowed_fan_ids)
                if self.require_fan_allowlist
                else None
            ),
            limit=5000,
        )
        if not candidates:
            self._presence_offset = 0
            return False
        if self._presence_offset >= len(candidates):
            self._presence_offset = 0
        batch = candidates[
            self._presence_offset:
            self._presence_offset + self.presence_batch_size
        ]
        if not batch:
            self._presence_offset = 0
            batch = candidates[: self.presence_batch_size]
        self._presence_offset = (
            self._presence_offset + len(batch)
        ) % len(candidates)

        by_id = {candidate.fan_id: candidate for candidate in batch}
        observations = self.client.get_user_presence(list(by_id))
        queued = 0
        any_online = False
        for provider_presence in observations:
            candidate = by_id.get(provider_presence.fan_id)
            if candidate is None:
                continue
            last_seen = (
                self._provider_datetime(provider_presence.last_seen_at)
                if provider_presence.last_seen_at is not None
                else None
            )
            observation = self.presence_repo.observe(
                creator_id=self.creator_id,
                fan_id=candidate.fan_id,
                last_seen_at=last_seen,
                provider_status_id=provider_presence.status_id,
                observed_at=now,
                online_window_seconds=self.online_window_seconds,
            )
            any_online = any_online or observation.status == "online"
            should_consider = observation.transitioned_online or (
                observation.first_observation
                and observation.status == "online"
                and self.outreach_existing_online
            )
            should_consider = should_consider and queue_outreach
            if not should_consider:
                continue
            eligible, reason = self.presence_repo.eligible_for_outreach(
                creator_id=self.creator_id,
                fan_id=candidate.fan_id,
                now=now,
                cooldown_hours=self.proactive_cooldown_hours,
                max_per_hour=self.max_proactive_per_hour,
                max_per_day=self.max_proactive_per_day,
                max_per_fan_per_day=(
                    self.max_proactive_per_fan_per_day
                ),
            )
            if not eligible:
                logger.info(
                    "Online outreach skipped for %s: %s",
                    candidate.fan_id,
                    reason,
                )
                continue
            transition_at = observation.last_seen_at or now
            synthetic_id = (
                f"online:{candidate.fan_id}:"
                f"{int(transition_at.timestamp() * 1000)}"
            )
            inbound_record, created = self.processing_repo.insert_inbound(
                creator_id=self.creator_id,
                platform_message_id=synthetic_id,
                fan_id=candidate.fan_id,
                chat_id=candidate.chat_id,
                content="fan recently became active",
                provider_created_at=transition_at,
                trigger_kind="online",
            )
            queued += int(created)
        if queued:
            logger.info("Queued %s online conversation opener(s)", queued)
        return bool(queued or any_online)

    def _poll_stalled_conversations(self) -> bool:
        """Queue one follow-up for each durable fan-response episode."""
        if (
            self.bot_mode != BotMode.CONVERSATION
            or not self.enable_stalled_outreach
        ):
            return False
        now = datetime.now(timezone.utc)
        if (
            self._last_stalled_scan_at is not None
            and (
                now - self._last_stalled_scan_at
            ).total_seconds() < self.stalled_scan_interval_seconds
        ):
            return False
        self._last_stalled_scan_at = now
        stalled_before = now - timedelta(hours=self.stalled_after_hours)
        candidates = self.presence_repo.stalled_candidates(
            self.creator_id,
            stalled_before=stalled_before,
            allowed_fan_ids=(
                set(self.allowed_fan_ids)
                if self.require_fan_allowlist
                else None
            ),
            limit=self.stalled_scan_batch_size,
        )
        work = []
        for candidate in candidates:
            digest = hashlib.sha256(
                (
                    f"{self.creator_id}\0{candidate.fan_id}\0"
                    f"{candidate.episode_key}"
                ).encode("utf-8")
            ).hexdigest()[:48]
            work.append(
                {
                    "creator_id": self.creator_id,
                    "platform_message_id": f"stalled:{digest}",
                    "fan_id": candidate.fan_id,
                    "chat_id": candidate.chat_id,
                    "content": candidate.episode_key,
                    "provider_created_at": now,
                    "trigger_kind": "stalled",
                }
            )
        queued = self.processing_repo.insert_inbound_many(work)
        if queued:
            logger.info(
                "Queued %s stalled conversation follow-up(s)",
                queued,
            )
        return bool(queued)

    def _fetch_incremental_chats(
        self,
        checkpoint: str | None,
    ) -> tuple[list[ChatInfo], str | None]:
        """Fetch newest pages only until the previous durable chat head."""
        if self.bot_mode == BotMode.CONVERSATION:
            unread: list[ChatInfo] = []
            offset: int | str | None = 0
            while offset is not None:
                page, offset = self.client.list_chats_page(
                    limit=100,
                    offset=offset,
                    order="unread",
                )
                unread.extend(
                    chat
                    for chat in page
                    if chat.unread_count > 0
                    and self._fan_allowed(chat.partner_account_id)
                )
            return unread, checkpoint
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
            for chat in page:
                if not self._fan_allowed(chat.partner_account_id):
                    continue
                if next_checkpoint is None:
                    next_checkpoint = self._chat_checkpoint(chat)
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

        if (
            self.bot_mode == BotMode.CONVERSATION
            and chat.unread_count <= 0
        ):
            self.state_repo.update_conversation_checkpoint(
                self.creator_id,
                chat.chat_id,
                last_platform_message_id=chat.last_message_id,
            )
            return 0

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
        messages_to_insert = inbound_messages
        if (
            self.bot_mode == BotMode.CONVERSATION
            and inbound_messages
        ):
            # A creator response newer than the unread fan window means the
            # conversation has already been handled outside this bot.
            newest_unseen = unseen[-1] if unseen else None
            if newest_unseen is not None and not newest_unseen.is_from_fan:
                messages_to_insert = []
            else:
                latest = inbound_messages[-1]
                combined = "\n".join(
                    (
                        message.content.strip()
                        if message.content.strip()
                        else "[sent an attachment]"
                    )
                    for message in inbound_messages
                )
                messages_to_insert = [
                    MessageInfo(
                        message_id=latest.message_id,
                        content=combined,
                        sender_id=latest.sender_id,
                        created_at=latest.created_at,
                        is_from_fan=True,
                        has_attachments=any(
                            message.has_attachments
                            for message in inbound_messages
                        ),
                        total_tip=sum(
                            message.total_tip
                            for message in inbound_messages
                        ),
                        attachments=[
                            attachment
                            for message in inbound_messages
                            for attachment in message.attachments
                        ],
                    )
                ]
        for message in messages_to_insert:
            inbound_record, created = self.processing_repo.insert_inbound(
                creator_id=self.creator_id,
                platform_message_id=message.message_id,
                fan_id=fan_id,
                chat_id=chat.chat_id,
                content=message.content,
                provider_created_at=self._provider_datetime(
                    message.created_at
                ),
                trigger_kind="unread",
                available_at=self._reply_available_at(
                    message.message_id
                ),
            )
            if created:
                self._attribute_inbound_outcome(
                    inbound_record,
                    self._provider_datetime(message.created_at),
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
                if inbound.trigger_kind in {"online", "stalled"}:
                    prepared = self._prepare_proactive_opener(inbound)
                else:
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
                    prepared = self._prepare_message(
                        chat,
                        message,
                        [message],
                        inbound_id=inbound.id,
                        trigger_kind=inbound.trigger_kind,
                    )
                self._persist_runtime_state(inbound.fan_id)
                if not prepared:
                    if (
                        self.bot_mode == BotMode.CONVERSATION
                        and inbound.trigger_kind == "unread"
                    ):
                        raise RuntimeError(
                            "conversation generation produced no approved reply"
                        )
                    self.processing_repo.complete_without_response(
                        inbound.id
                    )
                    return True
                outbound = self._coerce_outbound(prepared)
                outbox, _ = self.processing_repo.enqueue_outbox(
                    inbound=inbound,
                    message=outbound,
                )
                unsupported = self._unsupported_reason(outbound)
                if unsupported:
                    self.processing_repo.complete_unsupported(
                        outbox.id,
                        unsupported,
                    )
                    logger.error(
                        "Blocked unsupported %s delivery for inbound %s: %s",
                        outbound.kind.value,
                        inbound.platform_message_id,
                        unsupported,
                    )
                    return True

            if outbox.status != OUTBOX_PENDING:
                return True
            sending = self.processing_repo.claim_outbox(outbox.id)
            if sending is None:
                return False
            try:
                sent = self._deliver_outbox(sending)
                if not sent.success or not sent.message_id:
                    raise RuntimeError(
                        "Provider did not confirm a sent message ID"
                    )
                raw_purchase_reference = getattr(
                    sent,
                    "purchase_reference_id",
                    None,
                )
                purchase_reference_id = (
                    raw_purchase_reference.strip()
                    if isinstance(raw_purchase_reference, str)
                    and raw_purchase_reference.strip()
                    else None
                )
                if (
                    sending.message_kind == OutboundKind.PPV.value
                    and not purchase_reference_id
                ):
                    raise RuntimeError(
                        "Provider did not return the PPV purchase reference"
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

            delivered_outbox, _ = self.processing_repo.complete_delivery(
                sending.id,
                sent.message_id,
                provider_purchase_ref=purchase_reference_id,
            )
            if self.bot_mode == BotMode.CONVERSATION:
                try:
                    stored_decision = self.conversation_decision_repo.get(
                        inbound.id,
                        creator_id=self.creator_id,
                    )
                    if stored_decision is not None:
                        self.conversation_outcome_repo.create_for_delivery(
                            decision_id=stored_decision.id,
                            inbound_message_id=inbound.id,
                            outbox_message_id=delivered_outbox.id,
                            creator_id=self.creator_id,
                            fan_id=sending.fan_id,
                            brain_version="current-hardened-v1",
                            model=stored_decision.model,
                            trigger_kind=inbound.trigger_kind,
                            sent_at=(
                                delivered_outbox.sent_at
                                or datetime.now(timezone.utc)
                            ),
                        )
                except Exception:
                    logger.exception(
                        "Failed to schedule conversation outcome for inbound %s",
                        inbound.id,
                    )
            self._record_sent_reply(
                sending.fan_id,
                sending.content,
                sent.message_id,
            )
            if inbound.trigger_kind == "online":
                self.presence_repo.mark_outreach_sent(
                    self.creator_id,
                    sending.fan_id,
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
                    retry_base_seconds=(
                        self.processing_retry_base_seconds
                    ),
                    retry_max_seconds=(
                        self.processing_retry_max_seconds
                    ),
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

    @staticmethod
    def _coerce_outbound(
        value: OutboundMessage | str,
    ) -> OutboundMessage:
        if isinstance(value, OutboundMessage):
            return value
        if isinstance(value, str):
            return OutboundMessage.text(value)
        raise TypeError("prepared response must be an outbound message")

    def _unsupported_reason(
        self,
        message: OutboundMessage,
    ) -> str | None:
        if (
            self.bot_mode == BotMode.CONVERSATION
            and message.kind != OutboundKind.TEXT
        ):
            return "conversation mode permits text messages only"
        if self.bot_mode == BotMode.CONVERSATION:
            sales_reason = self.conversation_policy.sales_reason(
                message.content
            )
            if sales_reason:
                return sales_reason
        capabilities = self.client.capabilities
        if (
            message.kind == OutboundKind.MEDIA
            and capabilities.supports_free_media_messages is not True
        ):
            return "configured provider does not support free media messages"
        if (
            message.kind == OutboundKind.PPV
            and capabilities.supports_paid_messages is not True
        ):
            return (
                "configured provider does not support paid/paywalled messages"
            )
        return None

    def _deliver_message(
        self,
        chat_id: str,
        message: OutboundMessage,
        *,
        preview_id: str | None = None,
    ):
        if (
            self.bot_mode == BotMode.CONVERSATION
            and message.kind != OutboundKind.TEXT
        ):
            raise RuntimeError(
                "conversation mode blocked non-text delivery"
            )
        if self.bot_mode == BotMode.CONVERSATION:
            sales_reason = self.conversation_policy.sales_reason(
                message.content
            )
            if sales_reason:
                raise RuntimeError(sales_reason)
        if message.kind == OutboundKind.TEXT:
            return self.client.send_message(chat_id, message.content)
        if message.kind == OutboundKind.MEDIA:
            return self.client.send_message(
                chat_id,
                message.content,
                media_ids=[
                    {"mediaId": media_id}
                    for media_id in message.media_ids
                ],
            )
        if len(message.media_ids) != 1:
            raise ValueError("PPV delivery requires exactly one media ID")
        return self.client.send_ppv(
            chat_id=chat_id,
            content=message.content,
            media_id=message.media_ids[0],
            price=message.price_millis / 1000,
            preview_id=preview_id,
        )

    def _deliver_outbox(self, outbox: OutboxMessageRecord):
        preview_id = None
        if (
            outbox.message_kind == OutboundKind.PPV.value
            and outbox.sequence_id is not None
            and outbox.sequence_step_id is not None
        ):
            sequence = self.sequence_repo.get_sequence(
                outbox.sequence_id
            )
            if sequence is not None:
                step = next(
                    (
                        item
                        for item in sequence.steps
                        if item.id == outbox.sequence_step_id
                    ),
                    None,
                )
                preview_id = step.preview_id if step is not None else None
        return self._deliver_message(
            outbox.chat_id,
            OutboundMessage(
                kind=OutboundKind(outbox.message_kind),
                content=outbox.content,
                media_ids=outbox.media_ids,
                price_millis=outbox.price_millis,
                sequence_id=outbox.sequence_id,
                sequence_step_id=outbox.sequence_step_id,
            ),
            preview_id=preview_id,
        )

    def toggle(self, force: Optional[bool] = None) -> bool:
        """Toggle bot on/off. Returns new enabled state.

        If force is True/False, set to that state; otherwise flip.
        """
        target = bool(force) if force is not None else not self.enabled
        if target and not self.launch_ready:
            raise LaunchGuardError(self.launch_block_reason)
        self.enabled = target
        logger.info(f"Bot {'enabled' if self.enabled else 'disabled'}")
        return self.enabled

    def _prepare_proactive_opener(
        self,
        inbound: InboundMessageRecord,
    ) -> OutboundMessage | None:
        """Generate one contextual, non-sales proactive conversation."""
        if (
            self.bot_mode != BotMode.CONVERSATION
            or not self.chat_responder
            or not self.chat_responder.enabled
        ):
            return None
        if (
            inbound.trigger_kind == "stalled"
            and not self._stalled_episode_is_current(inbound)
        ):
            return None
        note = self.note_repo.get(inbound.fan_id, self.creator_id)
        self._backfill_memory_v2(note)
        history = (
            self.message_store.get_recent_context(
                inbound.fan_id,
                self.creator_id,
                limit=20,
            )
            if self.message_store
            else ""
        )
        guidance = (
            self.chat_guidance.snapshot()
            if self.chat_guidance is not None
            else None
        )
        return self._conversation_brain_reply(
            inbound_id=inbound.id,
            trigger_kind=inbound.trigger_kind,
            fan_id=inbound.fan_id,
            persona=self.persona,
            history=history,
            fan_message=None,
            known_facts=self._fan_memory(note),
            display_name=note.display_name if note else None,
            proactive=True,
            proactive_kind=inbound.trigger_kind,
            chat_instructions=(
                guidance.chat_instructions if guidance else ""
            ),
            brand_bible=guidance.brand_bible if guidance else "",
        )

    def _stalled_episode_is_current(
        self,
        inbound: InboundMessageRecord,
    ) -> bool:
        if self.message_store is None:
            return False
        latest = self.message_store.get_latest_message(
            inbound.fan_id,
            self.creator_id,
        )
        if (
            latest is None
            or latest["sender"] != "creator"
            or latest["created_at"] is None
        ):
            return False
        latest_at = datetime.fromisoformat(latest["created_at"])
        if latest_at.tzinfo is None:
            latest_at = latest_at.replace(tzinfo=timezone.utc)
        stalled_before = datetime.now(timezone.utc) - timedelta(
            hours=self.stalled_after_hours
        )
        if latest_at.astimezone(timezone.utc) > stalled_before:
            return False
        latest_fan = self.message_store.get_latest_message(
            inbound.fan_id,
            self.creator_id,
            sender="fan",
        )
        episode_key = "no-fan-message"
        if latest_fan is not None:
            episode_key = (
                latest_fan["message_id"]
                or latest_fan["created_at"]
                or episode_key
            )
        return inbound.content == episode_key

    def _prepare_message(
        self,
        chat: ChatInfo,
        latest: MessageInfo,
        messages: list[MessageInfo] | None = None,
        *,
        inbound_id: int | None = None,
        trigger_kind: str = "unread",
    ) -> OutboundMessage | None:
        """Load persistent state and produce one policy-approved response."""
        fan_id = chat.partner_account_id
        messages = messages or [latest]

        self.state_repo.ensure_conversation(
            self.creator_id,
            fan_id,
            chat.chat_id,
            display_name=chat.partner_display_name,
        )

        # Get or create fan session
        if fan_id not in self.sessions:
            session, durable_state = self.state_repo.load_session(
                self.creator_id,
                fan_id,
            )
            self.sessions[fan_id] = session
            self._runtime_state_versions[fan_id] = durable_state.version
            self._extract_counters[fan_id] = durable_state.extract_counter
            self.rhythm_engines[fan_id] = self.state_repo.restore_rhythm(
                durable_state
            )

        # Get fan notes
        note = self.note_repo.get(fan_id, self.creator_id)
        self._backfill_memory_v2(note)
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
                    recent = self.message_store.get_history(
                        fan_id,
                        self.creator_id,
                        limit=8,
                    )
                    fan_texts = [
                        message["content"]
                        for message in recent
                        if message["sender"] == "fan"
                    ]
                    if self.memory_extraction_service is not None:
                        self.memory_extraction_service.submit(
                            creator_id=self.creator_id,
                            fan_id=fan_id,
                            fan_texts=fan_texts,
                            source_message_id=latest.message_id,
                            source_timestamp=self._provider_datetime(
                                latest.created_at
                            ),
                        )
                except Exception:
                    logger.exception(
                        "Failed to submit memory extraction for fan %s",
                        fan_id,
                    )

        if self.bot_mode == BotMode.CONVERSATION:
            if not self.chat_responder or not self.chat_responder.enabled:
                return None
            history = (
                self.message_store.get_recent_context(
                    fan_id,
                    self.creator_id,
                    limit=20,
                )
                if self.message_store
                else ""
            )
            guidance = (
                self.chat_guidance.snapshot()
                if self.chat_guidance is not None
                else None
            )
            return self._conversation_brain_reply(
                inbound_id=inbound_id,
                trigger_kind=trigger_kind,
                fan_id=fan_id,
                persona=self.persona,
                history=history,
                fan_message=latest.content,
                known_facts=self._fan_memory(note),
                display_name=(
                    note.display_name
                    if note and note.display_name
                    else chat.partner_display_name
                ),
                proactive=False,
                chat_instructions=(
                    guidance.chat_instructions if guidance else ""
                ),
                brand_bible=guidance.brand_bible if guidance else "",
            )

        # ─── DECISION PIPELINE ───────────────────────────

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
                reply = self._prepare_premium_offer(fan_id, note)
            else:
                # 4. Generate contextual reply based on funnel stage
                reply = self._generate_reply(
                    chat.chat_id, fan_id, latest, session, note
                )

        if reply:
            outbound = self._coerce_outbound(reply)
            # Repair explicit persona phrases before final policy validation.
            validation = self.validator.validate(outbound.content)
            if not validation.passed:
                logger.warning(
                    f"Persona violation for {fan_id}: {validation.violations}"
                )
                # Fix: strip forbidden phrases
                for phrase in self.persona.forbidden_phrases:
                    outbound = outbound.with_content(
                        outbound.content.replace(
                            phrase,
                            self.persona.pet_names[0]
                            if self.persona.pet_names
                            else "babe",
                        )
                    )
            approved = self._style_and_approve(
                fan_id,
                outbound.content,
            )
            return outbound.with_content(approved) if approved else None
        return None

    # ─── REPLY GENERATION ───────────────────────────────

    def _generate_reply(
        self,
        chat_id: str,
        fan_id: str,
        message: MessageInfo,
        session: FanSession,
        note: FanNote,
    ) -> OutboundMessage | str | None:
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
            # Select the next offer as a typed PPV intent. Provider capability
            # validation happens before any delivery attempt.
            if funnel.can_send_ppv():
                result = self.sequence_engine.get_next_ppv(fan_id, "offer", fan_total_spent=note.total_spent if note else 0)
                if result:
                    sequence, step = result
                    if sequence.id is None or step.id is None:
                        logger.error(
                            "Cannot prepare PPV without sequence provenance"
                        )
                        return None
                    content = (
                        step.offer_script
                        or step.tease_script
                        or self.variation.pick("push")
                    )
                    return OutboundMessage.ppv(
                        content=content,
                        media_ids=(step.media_id,),
                        price_millis=int(round(step.price * 1000)),
                        sequence_id=sequence.id,
                        sequence_step_id=step.id,
                    )

                logger.warning(
                    "PPV offer skipped for %s: no configured media sequence",
                    fan_id,
                )
                return None

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

    def _approve_conversation_text(
        self,
        fan_id: str,
        text: str | None,
    ) -> str | None:
        if not text:
            return None
        sales_reason = self.conversation_policy.sales_reason(text)
        if sales_reason:
            logger.warning(
                "Conversation response rejected for %s: %s",
                fan_id,
                sales_reason,
            )
            return None
        approved = self._style_and_approve(fan_id, text)
        if not approved:
            return None
        sales_reason = self.conversation_policy.sales_reason(approved)
        if sales_reason:
            logger.warning(
                "Styled conversation response rejected for %s: %s",
                fan_id,
                sales_reason,
            )
            return None
        return approved

    def _conversation_brain_reply(
        self,
        *,
        inbound_id: int | None,
        trigger_kind: str,
        fan_id: str,
        **context,
    ) -> OutboundMessage | None:
        """Generate the authoritative live turn with durable continuity."""
        if not self.chat_responder:
            return None
        recent_decisions = self.conversation_decision_repo.latest_for_fan(
            creator_id=self.creator_id,
            fan_id=fan_id,
            limit=5,
        )
        previous = recent_decisions[0].decision if recent_decisions else None
        brain_state = self.brain_state_repo.get_or_create(
            self.creator_id,
            fan_id,
        )
        memories = self.memory_v2_repo.relevant(
            creator_id=self.creator_id,
            fan_id=fan_id,
            limit=20,
        )
        episodes = self.episode_repo.recent(
            creator_id=self.creator_id,
            fan_id=fan_id,
            limit=3,
        )
        known_facts = list(context.get("known_facts") or [])
        for memory in memories:
            display = str(memory["display_value"])
            if display in known_facts:
                continue
            known_facts.append(
                display
                if float(memory["confidence"] or 0) >= 0.8
                else "Uncertain memory; do not state as fact: " + display
            )
        episode_summaries = [
            json.dumps(
                {
                    "topics": episode.get("main_topics") or [],
                    "tone": episode.get("emotional_tone"),
                    "resolved": episode.get("resolved_threads") or [],
                    "unresolved": episode.get("unresolved_threads") or [],
                    "future_callback": episode.get("future_callback"),
                    "source_range": [
                        episode.get("source_start_message_id"),
                        episode.get("source_end_message_id"),
                    ],
                },
                ensure_ascii=False,
                default=str,
            )
            for episode in episodes
        ]
        context["known_facts"] = known_facts
        context["episode_summaries"] = episode_summaries
        context["conversation_state"] = {
            key: brain_state.get(key)
            for key in (
                "relationship_stage",
                "current_mood",
                "current_energy",
                "engagement_estimate",
                "current_objective",
                "current_tactic",
                "active_thread",
                "recent_objectives",
                "recent_tactics",
            )
        }
        context["question_streak"] = int(brain_state["question_streak"])
        context["pet_name_streak"] = int(brain_state["pet_name_streak"])
        context["previous_decision"] = (
            {
                "objective": previous.objective,
                "tactic": previous.tactic,
                "open_thread": previous.open_thread,
            }
            if previous is not None
            else None
        )
        context["recent_objectives"] = [
            item.decision.objective for item in recent_decisions
        ]
        context["recent_tactics"] = [
            item.decision.tactic for item in recent_decisions
        ]
        decision = self.chat_responder.decide(**context)
        recent_creator_messages: list[str] = []
        if self.message_store is not None:
            try:
                recent_creator_messages = [
                    item["content"]
                    for item in self.message_store.get_history(
                        fan_id,
                        self.creator_id,
                        limit=12,
                    )
                    if item["sender"] == "creator"
                ]
            except Exception:
                logger.exception("Failed to load creator repetition context")
        if decision is None:
            fallback = self._safe_conversation_fallback(
                trigger_kind=trigger_kind,
                fan_message=context.get("fan_message"),
                question_streak=int(brain_state["question_streak"]),
            )
            if fallback:
                decision = ConversationDecision.from_model_output(
                    fallback,
                    proactive_kind=(
                        trigger_kind
                        if trigger_kind in {"online", "stalled"}
                        else None
                    ),
                )
        if decision is None:
            return None
        gate = self.brain_quality_gate.evaluate(
            decision.final_message,
            recent_creator_messages=recent_creator_messages,
            question_streak=int(brain_state["question_streak"]),
            pet_name_streak=int(brain_state["pet_name_streak"]),
            pet_names=tuple(self.persona.pet_names),
            hard_boundaries=(
                list(self.persona.content_boundaries)
                + [
                    memory["display_value"]
                    for memory in memories
                    if memory["memory_type"] == "boundary"
                    and memory["status"] == "active"
                ]
            ),
            max_length=500,
        )
        if not gate.approved:
            logger.warning(
                "Conversation quality gate rejected %s: %s",
                fan_id,
                gate.reason_codes,
            )
            return None
        approved = self._approve_conversation_text(
            fan_id,
            decision.final_message,
        )
        if not approved:
            return None
        approved_decision = decision.with_approved_message(approved)
        if inbound_id is not None:
            self.conversation_decision_repo.save(
                inbound_message_id=inbound_id,
                creator_id=self.creator_id,
                fan_id=fan_id,
                trigger_kind=trigger_kind,
                decision=approved_decision,
                model=self.chat_responder.model,
            )
        recent_objectives = (
            [approved_decision.objective]
            + list(brain_state["recent_objectives"] or [])
        )[:5]
        recent_tactics = (
            [approved_decision.tactic]
            + list(brain_state["recent_tactics"] or [])
        )[:5]
        fan_text = str(context.get("fan_message") or "")
        fan_signal_length = sum(character.isalnum() for character in fan_text)
        fan_energy = (
            "high"
            if fan_signal_length >= 120 or fan_text.count("!") >= 2
            else "low"
            if fan_signal_length < 12
            else "medium"
        )
        creator_energy = (
            "high"
            if len(approved) >= 180 or approved.count("!") >= 2
            else "low"
            if len(approved) < 25
            else "medium"
        )
        relationship_stage = (
            "new"
            if not recent_decisions
            else "developing"
            if len(recent_decisions) < 5
            else "established"
        )
        engagement_estimate = (
            0.8 if fan_energy == "high" else 0.35 if fan_energy == "low" else 0.6
        )
        lower = approved.casefold()
        used_pet_name = any(
            name.casefold() in lower for name in self.persona.pet_names
        )
        self.brain_state_repo.update(
            creator_id=self.creator_id,
            fan_id=fan_id,
            expected_version=int(brain_state["state_version"]),
            changes={
                "relationship_stage": relationship_stage,
                "current_mood": approved_decision.fan_state,
                "current_energy": fan_energy,
                "engagement_estimate": engagement_estimate,
                "last_fan_energy": fan_energy,
                "last_creator_energy": creator_energy,
                "current_objective": approved_decision.objective,
                "current_tactic": approved_decision.tactic,
                "active_thread": approved_decision.open_thread,
                "recent_objectives": recent_objectives,
                "recent_tactics": recent_tactics,
                "question_streak": (
                    int(brain_state["question_streak"]) + 1
                    if "?" in approved
                    else 0
                ),
                "pet_name_streak": (
                    int(brain_state["pet_name_streak"]) + 1
                    if used_pet_name
                    else 0
                ),
            },
        )
        if inbound_id is not None and self.shadow_brain_service is not None:
            try:
                persona_snapshot = (
                    self.persona.model_dump()
                    if hasattr(self.persona, "model_dump")
                    else {}
                )
                self.shadow_brain_service.submit(
                    inbound_id=inbound_id,
                    fan_id=fan_id,
                    trigger_kind=trigger_kind,
                    context={
                        "fan_message": context.get("fan_message"),
                        "history": context.get("history"),
                        "known_facts": known_facts,
                        "episode_summaries": episode_summaries,
                        "previous_decision": context.get("previous_decision"),
                        "conversation_state": dict(brain_state),
                        "persona": persona_snapshot,
                        "chat_instructions": context.get("chat_instructions"),
                        "brand_bible": context.get("brand_bible"),
                        "recent_creator_messages": recent_creator_messages,
                        "question_streak": brain_state["question_streak"],
                        "pet_name_streak": brain_state["pet_name_streak"],
                        "hard_boundaries": (
                            list(self.persona.content_boundaries)
                            + [
                                memory["display_value"]
                                for memory in memories
                                if memory["memory_type"] == "boundary"
                                and memory["status"] == "active"
                            ]
                        ),
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to submit shadow analysis for inbound %s",
                    inbound_id,
                )
        if self.episode_service is not None:
            try:
                self.episode_service.submit(fan_id)
            except Exception:
                logger.exception(
                    "Failed to submit episode generation for fan %s",
                    fan_id,
                )
        return OutboundMessage.text(approved)

    @staticmethod
    def _safe_conversation_fallback(
        *,
        trigger_kind: str,
        fan_message: str | None,
        question_streak: int,
    ) -> str | None:
        if trigger_kind == "online":
            return "hey, how's your day going?"
        if trigger_kind == "stalled":
            return "how's your day going?"
        if not str(fan_message or "").strip():
            return None
        if question_streak >= 2:
            return "i'm listening"
        return "tell me a little more?"

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
        """Prepare an already-attributed aftercare plan."""
        plan = self.aftercare.plans.get(fan_id)
        if plan is None:
            logger.error(
                "Aftercare skipped for %s: no attributed purchase plan",
                fan_id,
            )
            return None
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
    ) -> OutboundMessage | None:
        """Prepare a typed premium intent without bypassing the outbox."""
        result = self.sequence_engine.get_next_ppv(fan_id, "offer", fan_total_spent=note.total_spent if note else 0)
        if result:
            sequence, step = result
            if step.price >= 25 or step.offer_script:
                if sequence.id is None or step.id is None:
                    logger.error(
                        "Cannot prepare premium PPV without provenance"
                    )
                    return None
                self.reciprocity.mark_premium_pitched(fan_id)
                content = (
                    step.offer_script
                    or step.tease_script
                    or self.variation.pick("premium_ppv")
                )
                return OutboundMessage.ppv(
                    content=content,
                    media_ids=(step.media_id,),
                    price_millis=int(round(step.price * 1000)),
                    sequence_id=sequence.id,
                    sequence_step_id=step.id,
                )
        logger.warning(
            "Premium offer skipped for %s: no attributable PPV sequence",
            fan_id,
        )
        return None

    def _days_since_last_purchase(self, note: Optional[FanNote]) -> int:
        if not note or not note.last_purchase_at:
            return 90  # default: treat as lapsed
        from datetime import datetime, timezone
        delta = datetime.now(timezone.utc) - note.last_purchase_at
        return delta.days

    def _init_purchase_cache(self) -> None:
        """Deprecated compatibility hook; purchases are provider-event driven."""
        return None

    def _has_classified(self, fan_id: str) -> bool:
        note = self.note_repo.get(fan_id, self.creator_id)
        return note is not None and note.relationship_stage.startswith("classified_")

    # ─── MESSAGE DEDUPLICATION ──────────────────────────

    def _persist_runtime_state(self, fan_id: str):
        session = self.sessions.get(fan_id)
        if session is None:
            return
        try:
            current = self.state_repo.load_state(
                self.creator_id,
                fan_id,
            )
            if current is not None:
                known_version = self._runtime_state_versions.get(fan_id)
                if (
                    known_version is not None
                    and current.version != known_version
                ):
                    session.funnel.level.number = max(
                        session.funnel.level.number,
                        current.escalation_level,
                    )
                    session.funnel.level.ppvs_bought = max(
                        session.funnel.level.ppvs_bought,
                        current.ppvs_bought,
                    )
                    session.funnel.consecutive_rejections = (
                        current.consecutive_rejections
                    )
                self._runtime_state_versions[fan_id] = current.version
            rhythm = self.rhythm_engines.get(fan_id)
            state = self.state_repo.capture_session(
                session,
                extract_counter=self._extract_counters.get(fan_id, 0),
                purchase_count_seen=(
                    current.purchase_count_seen if current else 0
                ),
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
