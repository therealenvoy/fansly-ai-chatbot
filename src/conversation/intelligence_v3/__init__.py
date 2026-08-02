"""Conversation Intelligence V3 contracts and fail-closed services."""

from src.conversation.intelligence_v3.contracts import (
    CandidateAssessment,
    CandidateDraft,
    HighEQPlan,
    RelationshipSnapshot,
)
from src.conversation.intelligence_v3.settings import V3RuntimeSettings
from src.conversation.intelligence_v3.corpus import (
    CorpusIngestor,
    compile_tiffany_corpus,
    load_compiled_corpus,
)

__all__ = [
    "CandidateAssessment",
    "CandidateDraft",
    "HighEQPlan",
    "RelationshipSnapshot",
    "V3RuntimeSettings",
    "CorpusIngestor",
    "compile_tiffany_corpus",
    "load_compiled_corpus",
]
