"""ScriptLibrary — load, catalogue, and retrieve script templates."""

from src.scripts.models import ScriptTemplate, ScriptCategory, ScriptVariable


# ---------------------------------------------------------------------------
# Builtin scripts: at minimum 3 welcome, 4 PPV, 4 reengage, 4 objection, 3 custom
# ---------------------------------------------------------------------------
BUILTIN_SCRIPTS: list[ScriptTemplate] = [
    # ── WELCOME (3) ──────────────────────────────────────────────────────
    ScriptTemplate(
        name="welcome_basic",
        category=ScriptCategory.WELCOME,
        description="Basic welcome message for new subscribers",
        messages=["Hey {fan_name}! Welcome to my page 💕 So glad you're here!"],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
        ],
    ),
    ScriptTemplate(
        name="welcome_personalized",
        category=ScriptCategory.WELCOME,
        description="Personalized welcome referencing fan preferences",
        messages=[
            "Hey {fan_name}! Welcome! 😍",
            "I noticed you love {fan_preference} content — you're gonna love what I have in store for you!",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="fan_preference", source="fan_notes.preferences.0", fallback="exclusive"),
        ],
    ),
    ScriptTemplate(
        name="welcome_vip",
        category=ScriptCategory.WELCOME,
        description="Welcome message for high-spending fans",
        messages=[
            "Oh wow {fan_name}, welcome back! 🌟",
            "As one of my favorite fans, I've got something special for you... stay tuned 😘",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
        ],
        conditions={"min_total_spent": 100.0},
    ),

    # ── PPV SOFT TEASE (1) ───────────────────────────────────────────────
    ScriptTemplate(
        name="ppv_soft_tease_generic",
        category=ScriptCategory.PPV_SOFT_TEASE,
        description="Soft tease hinting at exclusive content",
        messages=[
            "I just dropped {content_detail} and honestly... it's one of my favorites 😏",
            "Wanna see what all the excitement is about?",
        ],
        variables=[
            ScriptVariable(name="content_detail", source="offer.description", fallback="something special"),
        ],
    ),

    # ── PPV DIRECT (1) ───────────────────────────────────────────────────
    ScriptTemplate(
        name="ppv_direct_exclusive",
        category=ScriptCategory.PPV_DIRECT,
        description="Direct PPV offer with price and urgency",
        messages=[
            "Hey {fan_name}! I've got {content_detail} ready for you 🔥",
            "Just ${price} for a limited time — don't miss out!",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="exclusive content"),
            ScriptVariable(name="price", source="offer.price", fallback="9.99"),
        ],
    ),

    # ── PPV BUNDLE (1) ───────────────────────────────────────────────────
    ScriptTemplate(
        name="ppv_bundle_deal",
        category=ScriptCategory.PPV_BUNDLE,
        description="Bundle offer for multiple content pieces",
        messages=[
            "Why settle for one when you can have it all? 😈",
            "My {bundle_name} bundle includes {bundle_items} for just ${bundle_price}!",
        ],
        variables=[
            ScriptVariable(name="bundle_name", source="offer.bundle_name", fallback="VIP"),
            ScriptVariable(name="bundle_items", source="offer.bundle_items", fallback="3 exclusive pieces"),
            ScriptVariable(name="bundle_price", source="offer.bundle_price", fallback="24.99"),
        ],
    ),

    # ── PPV LIMITED TIME (1) ─────────────────────────────────────────────
    ScriptTemplate(
        name="ppv_limited_flash",
        category=ScriptCategory.PPV_LIMITED_TIME,
        description="Flash sale / limited time offer",
        messages=[
            "⏰ FLASH SALE — 50% off {content_detail} for the next 2 hours!",
            "Usually ${regular_price}, now just ${sale_price}. Grab it before {fan_name} does! 😉",
        ],
        variables=[
            ScriptVariable(name="content_detail", source="offer.description", fallback="my hottest content"),
            ScriptVariable(name="regular_price", source="offer.regular_price", fallback="19.99"),
            ScriptVariable(name="sale_price", source="offer.sale_price", fallback="9.99"),
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="someone else"),
        ],
    ),

    # ── REENGAGE 3DAY (1) ────────────────────────────────────────────────
    ScriptTemplate(
        name="reengage_3day_checkin",
        category=ScriptCategory.REENGAGE_3DAY,
        description="Check-in after 3 days of inactivity",
        messages=[
            "Hey {fan_name}! It's been a few days... missing you! 💭",
            "I just posted {content_detail} and thought you'd wanna see it first 😘",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="some new content"),
        ],
    ),

    # ── REENGAGE 7DAY (1) ────────────────────────────────────────────────
    ScriptTemplate(
        name="reengage_7day_comeback",
        category=ScriptCategory.REENGAGE_7DAY,
        description="Re-engagement after 1 week of inactivity",
        messages=[
            "It's been a whole week {fan_name}! 😢 I've been thinking about you...",
            "Come back and see what you've been missing — {content_detail} is waiting 💋",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="something incredible"),
        ],
    ),

    # ── REENGAGE 14DAY (1) ───────────────────────────────────────────────
    ScriptTemplate(
        name="reengage_14day_special",
        category=ScriptCategory.REENGAGE_14DAY,
        description="Special offer to bring back 2-week inactive fans",
        messages=[
            "Two weeks is too long, {fan_name}! 🥺",
            "Here's a special comeback offer — {offer_pitch} — just for you 💕",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="offer_pitch", source="offer.pitch", fallback="20% off your next purchase"),
        ],
    ),

    # ── REENGAGE 30DAY (1) ───────────────────────────────────────────────
    ScriptTemplate(
        name="reengage_30day_miss_you",
        category=ScriptCategory.REENGAGE_30DAY,
        description="Win-back message after 30 days",
        messages=[
            "A whole month?! {fan_name}, I've saved the best for you 😈",
            "I've been creating {content_detail} and I NEED you to see it. First look? 👀",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="the sexiest content yet"),
        ],
    ),

    # ── OBJECTION PRICE (1) ──────────────────────────────────────────────
    ScriptTemplate(
        name="objection_price_too_high",
        category=ScriptCategory.OBJECTION_PRICE,
        description="Handle price objection by emphasizing value",
        messages=[
            "I totally get it {fan_name}! Quality doesn't come cheap though 💎",
            "This {content_detail} took me hours to create... but because I like you, how about ${discount_price}?",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="content"),
            ScriptVariable(name="discount_price", source="offer.discount_price", fallback="a special price"),
        ],
    ),

    # ── OBJECTION FREE (1) ───────────────────────────────────────────────
    ScriptTemplate(
        name="objection_want_free",
        category=ScriptCategory.OBJECTION_FREE,
        description="Handle 'can I get it for free' objection",
        messages=[
            "Aww {fan_name}, you're adorable 😘 Free content is what my page is for!",
            "But {content_detail} is something extra special I put my heart into... it's worth it, promise 💕",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="this exclusive piece"),
        ],
    ),

    # ── OBJECTION HESITATE (1) ───────────────────────────────────────────
    ScriptTemplate(
        name="objection_hesitating",
        category=ScriptCategory.OBJECTION_HESITATE,
        description="Handle hesitation / 'maybe later' objection",
        messages=[
            "No pressure at all {fan_name}! 😊",
            "Just know that {content_detail} won't be around forever... I'd hate for you to miss it! 💋",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="this offer"),
        ],
    ),

    # ── OBJECTION ALREADY BOUGHT (1) ───────────────────────────────────
    ScriptTemplate(
        name="objection_already_bought",
        category=ScriptCategory.OBJECTION_ALREADY_BOUGHT,
        description="Fan already purchased — upsell or redirect",
        messages=[
            "Oh you already have that one? You're a true fan 😍",
            "In that case... have you seen {content_detail}? It's brand new and even better! 🔥",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="offer.description", fallback="my latest release"),
        ],
    ),

    # ── CUSTOM INTAKE (1) ────────────────────────────────────────────────
    ScriptTemplate(
        name="custom_intake_preferences",
        category=ScriptCategory.CUSTOM_INTAKE,
        description="Gather preferences for custom content requests",
        messages=[
            "You want something custom? I LOVE creating personal content! 💖",
            "Tell me everything — what kind of vibe, any specific outfits, {question_detail}?",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="question_detail", source="custom.detail_question", fallback="any special requests"),
        ],
    ),

    # ── CUSTOM UPSELL (1) ────────────────────────────────────────────────
    ScriptTemplate(
        name="custom_upsell_premium",
        category=ScriptCategory.CUSTOM_UPSELL,
        description="Upsell to premium custom content tier",
        messages=[
            "So {fan_name}, for the basic custom that's ${base_price}...",
            "BUT if you want the premium treatment — {premium_details} — that's just ${premium_price} 😈",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="base_price", source="custom.base_price", fallback="X"),
            ScriptVariable(name="premium_details", source="custom.premium_details", fallback="extra photos + voice note"),
            ScriptVariable(name="premium_price", source="custom.premium_price", fallback="Y"),
        ],
    ),

    # ── CUSTOM DELIVERY (1) ──────────────────────────────────────────────
    ScriptTemplate(
        name="custom_delivery_message",
        category=ScriptCategory.CUSTOM_DELIVERY,
        description="Deliver completed custom content",
        messages=[
            "Surprise {fan_name}! Your custom {content_detail} is ready! 🎁",
            "I had SO much fun making this for you... hope you love it as much as I did! 😘",
        ],
        variables=[
            ScriptVariable(name="fan_name", source="fan_notes.display_name", fallback="friend"),
            ScriptVariable(name="content_detail", source="custom.content_type", fallback="content"),
        ],
    ),
]


class ScriptLibrary:
    """Catalogue of script templates with retrieval methods."""

    def __init__(self) -> None:
        self.templates: list[ScriptTemplate] = []

    def load_builtin(self) -> None:
        """Populate the library with the built-in script templates."""
        self.templates = list(BUILTIN_SCRIPTS)

    def apply_overrides(
        self,
        templates: list[ScriptTemplate],
    ) -> None:
        """Overlay durable creator scripts by name without duplicating them."""
        by_name = {template.name: template for template in self.templates}
        for template in templates:
            by_name[template.name] = template
        self.templates = list(by_name.values())

    def get_by_category(self, category: ScriptCategory) -> list[ScriptTemplate]:
        """Return all templates belonging to *category*."""
        return [t for t in self.templates if t.category == category]

    def get(self, name: str) -> ScriptTemplate | None:
        """Return the template with the given *name*, or None if not found."""
        for t in self.templates:
            if t.name == name:
                return t
        return None
