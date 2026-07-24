"""PersonaLoader — loads persona YAML configs from disk."""

import os
import yaml

from src.persona.models import PersonaDocument


class PersonaLoader:
    """Reads {creator_id}.yaml from config/creators/ and returns PersonaDocument.

    Args:
        config_dir: Directory containing persona YAML files (default: config/creators).
    """

    def __init__(self, config_dir: str = "config/creators"):
        self.config_dir = config_dir

    def load(self, creator_id: str) -> PersonaDocument:
        """Load a persona configuration for the given creator.

        Args:
            creator_id: The creator identifier (matches filename without .yaml).

        Returns:
            PersonaDocument populated with the YAML configuration.

        Raises:
            FileNotFoundError: If the config file does not exist.
        """
        filepath = os.path.join(self.config_dir, f"{creator_id}.yaml")

        if not os.path.isfile(filepath):
            raise FileNotFoundError(
                f"Persona config not found for creator '{creator_id}': {filepath}"
            )

        with open(filepath, "r") as f:
            data = yaml.safe_load(f)

        data["creator_id"] = creator_id
        return PersonaDocument(**data)