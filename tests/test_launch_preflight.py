from src.launch_preflight import check_environment


def _valid_environment():
    return {
        "DATABASE_URL": "postgresql://user:pass@db:5432/app",
        "FANSLY_PROVIDER": "fanslyapi",
        "FANSLY_API_KEY": "secret-token",
        "DASHBOARD_USER": "operator",
        "DASHBOARD_PASSWORD": "correct-horse-battery-staple",
        "CONTROLLED_LAUNCH": "true",
        "BOT_ENABLED_DEFAULT": "false",
        "FAN_ALLOWLIST": "pilot-1",
        "CREATOR_ID": "sunny_charm",
    }


def test_valid_launch_environment_passes(tmp_path):
    persona = tmp_path / "config" / "creators" / "sunny_charm.yaml"
    persona.parent.mkdir(parents=True)
    persona.write_text("creator_id: sunny_charm", encoding="utf-8")

    assert check_environment(
        _valid_environment(),
        project_root=tmp_path,
    ) == []


def test_unsafe_launch_environment_reports_all_blockers(tmp_path):
    environment = _valid_environment()
    environment.update({
        "DATABASE_URL": "sqlite:///data/app.db",
        "FANSLY_PROVIDER": "other",
        "FANSLY_API_KEY": "",
        "DASHBOARD_USER": "",
        "DASHBOARD_PASSWORD": "short",
        "FAN_ALLOWLIST": "",
        "BOT_ENABLED_DEFAULT": "true",
    })

    errors = check_environment(environment, project_root=tmp_path)

    assert "DATABASE_URL must use PostgreSQL" in errors
    assert "FANSLY_PROVIDER must be fanslyapi" in errors
    assert "FAN_ALLOWLIST must contain at least one pilot fan" in errors
    assert "BOT_ENABLED_DEFAULT must remain false for launch" in errors
    assert any("persona YAML is missing" in error for error in errors)
