"""PersonaValidator — checks messages against persona voice constraints."""

from dataclasses import dataclass, field

from src.persona.models import PersonaDocument


@dataclass
class ValidationResult:
    """Result of a voice consistency validation check.

    Attributes:
        passed: True if the message passes all voice checks.
        violations: List of human-readable descriptions of each violation.
    """

    passed: bool
    violations: list[str] = field(default_factory=list)


class PersonaValidator:
    """Validates messages against a creator's persona configuration.

    Checks include:
    - Forbidden phrases (case-insensitive)
    """

    def __init__(self, persona: PersonaDocument):
        self.persona = persona

    def validate(self, message: str) -> ValidationResult:
        """Check a message for voice consistency violations.

        Args:
            message: The message text to validate.

        Returns:
            ValidationResult indicating pass/fail and listing any violations.
        """
        violations: list[str] = []
        message_lower = message.lower()

        for phrase in self.persona.forbidden_phrases:
            if phrase.lower() in message_lower:
                violations.append(f"forbidden: {phrase}")

        passed = len(violations) == 0
        return ValidationResult(passed=passed, violations=violations)