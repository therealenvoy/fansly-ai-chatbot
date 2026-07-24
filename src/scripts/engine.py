"""ScriptEngine — variable resolution, condition checking, and stage-based script selection."""

import re

from src.scripts.models import ScriptTemplate, ScriptCategory
from src.scripts.loader import ScriptLibrary


# Map friendly stage names to ScriptCategory values used for lookup.
STAGE_TO_CATEGORY: dict[str, ScriptCategory] = {
    "welcome": ScriptCategory.WELCOME,
    "tease": ScriptCategory.PPV_SOFT_TEASE,
    "offer_direct": ScriptCategory.PPV_DIRECT,
    "offer_bundle": ScriptCategory.PPV_BUNDLE,
    "offer_limited": ScriptCategory.PPV_LIMITED_TIME,
    "reengage_3day": ScriptCategory.REENGAGE_3DAY,
    "reengage_7day": ScriptCategory.REENGAGE_7DAY,
    "reengage_14day": ScriptCategory.REENGAGE_14DAY,
    "reengage_30day": ScriptCategory.REENGAGE_30DAY,
    "objection_price": ScriptCategory.OBJECTION_PRICE,
    "objection_free": ScriptCategory.OBJECTION_FREE,
    "objection_hesitate": ScriptCategory.OBJECTION_HESITATE,
    "objection_already_bought": ScriptCategory.OBJECTION_ALREADY_BOUGHT,
    "custom_intake": ScriptCategory.CUSTOM_INTAKE,
    "custom_upsell": ScriptCategory.CUSTOM_UPSELL,
    "custom_delivery": ScriptCategory.CUSTOM_DELIVERY,
}

# Supported condition keys and their corresponding context keys.
CONDITION_CHECKS: dict[str, tuple[str, str]] = {
    # condition_key -> (context_key, comparison_op)
    "min_rapport_messages": ("rapport_messages", ">="),
    "max_previous_purchases": ("previous_purchases", "<="),
    "min_total_spent": ("total_spent", ">="),
}


class ScriptEngine:
    """Resolves script variables, checks conditions, and selects scripts by stage."""

    def __init__(self, library: ScriptLibrary) -> None:
        self._library = library

    # ── variable resolution ───────────────────────────────────────────

    def resolve(self, template: ScriptTemplate, context: dict) -> list[str]:
        """Fill all {variable_name} placeholders in *template.messages* from *context*.

        Returns a list of resolved message strings.
        """
        # Build a lookup: variable name → resolved value
        values: dict[str, str] = {}
        for var in template.variables:
            values[var.name] = var.resolve(context)

        # Substitute placeholders in each message
        resolved: list[str] = []
        for message in template.messages:
            resolved_msg = message
            # Use regex so we can gracefully skip unknown {placeholders}
            def _replace(m: re.Match[str]) -> str:
                key = m.group(1)
                return values.get(key, m.group(0))  # leave unknown as-is

            resolved_msg = re.sub(r"\{(\w+)\}", _replace, message)
            resolved.append(resolved_msg)

        return resolved

    # ── condition checking ────────────────────────────────────────────

    def check_conditions(self, template: ScriptTemplate, context: dict) -> bool:
        """Return True if all conditions in *template.conditions* pass against *context*.

        Supported conditions:
            min_rapport_messages  — context["rapport_messages"] >= value
            max_previous_purchases — context["previous_purchases"] <= value
            min_total_spent       — context["total_spent"] >= value

        Unknown condition keys are silently ignored.
        Templates with no conditions always pass.
        """
        if not template.conditions:
            return True

        for key, threshold in template.conditions.items():
            if key not in CONDITION_CHECKS:
                continue  # unknown condition key → skip

            ctx_key, op = CONDITION_CHECKS[key]
            actual = context.get(ctx_key, 0)

            if op == ">=":
                if actual < threshold:
                    return False
            elif op == "<=":
                if actual > threshold:
                    return False

        return True

    # ── stage-based selection ─────────────────────────────────────────

    def get_script_for_stage(
        self, stage: str, context: dict
    ) -> ScriptTemplate | None:
        """Return the first template matching *stage* that also passes conditions.

        Returns None if the stage is unrecognized or no templates match.
        """
        category = STAGE_TO_CATEGORY.get(stage)
        if category is None:
            return None

        candidates = self._library.get_by_category(category)
        for template in candidates:
            if self.check_conditions(template, context):
                return template

        return None