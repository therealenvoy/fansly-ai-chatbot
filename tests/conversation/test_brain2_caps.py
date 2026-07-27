from src.conversation.brain2_repository import StrategicUsageCapRepository
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository


def test_strategic_hourly_and_daily_call_reservation_is_atomic():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    repository = StrategicUsageCapRepository(engine)

    assert repository.reserve(
        creator_id="creator-a",
        calls=3,
        hourly_limit=6,
        daily_limit=9,
    ) is True
    assert repository.reserve(
        creator_id="creator-a",
        calls=3,
        hourly_limit=6,
        daily_limit=9,
    ) is True
    assert repository.reserve(
        creator_id="creator-a",
        calls=3,
        hourly_limit=6,
        daily_limit=9,
    ) is False
