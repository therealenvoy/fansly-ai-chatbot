import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _requirement_names(path: Path) -> set[str]:
    names = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-r")):
            continue
        names.add(
            line.split("[", 1)[0]
            .split("=", 1)[0]
            .split("<", 1)[0]
            .split(">", 1)[0]
            .strip()
            .lower()
        )
    return names


def test_production_requirements_exclude_optional_ml_stack():
    runtime = _requirement_names(ROOT / "requirements.txt")

    assert {
        "alembic",
        "httpx",
        "psycopg2-binary",
        "pydantic",
        "python-dotenv",
        "pyyaml",
        "sqlalchemy",
    } <= runtime
    assert runtime.isdisjoint(
        {
            "torch",
            "transformers",
            "sentence-transformers",
            "chromadb",
            "faiss-cpu",
            "pandas",
            "scikit-learn",
        }
    )


def test_development_requirements_include_runtime_and_test_tools():
    content = (ROOT / "requirements-dev.txt").read_text(
        encoding="utf-8"
    )
    development = _requirement_names(ROOT / "requirements-dev.txt")

    assert "-r requirements.txt" in content
    assert {"pytest", "fastapi", "torch", "transformers"} <= development


def test_dockerfile_copies_only_runtime_inputs_and_has_healthcheck():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "pip install --no-cache-dir --requirement requirements.txt" in dockerfile
    assert "COPY src ./src" in dockerfile
    assert "COPY migrations ./migrations" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/ready" in dockerfile
    assert 'CMD ["python", "-m", "src.main"]' in dockerfile


def test_railway_config_enforces_healthcheck_and_restart_policy():
    config = json.loads(
        (ROOT / "railway.json").read_text(encoding="utf-8")
    )

    assert config["build"]["builder"] == "DOCKERFILE"
    assert config["deploy"] == {
        "healthcheckPath": "/ready",
        "healthcheckTimeout": 120,
        "restartPolicyType": "ON_FAILURE",
        "restartPolicyMaxRetries": 10,
    }


def test_docker_context_excludes_secrets_history_and_test_artifacts():
    ignored = set(
        (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert {
        ".git",
        ".env",
        ".env.*",
        "data",
        "tests",
        ".runtime-deps",
    } <= ignored


def test_production_uptime_monitor_checks_ready_twice():
    workflow = (
        ROOT / ".github" / "workflows" / "production-monitor.yml"
    ).read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "*/15 * * * *" in workflow
    assert "https://sunny-charm-production.up.railway.app/ready" in workflow
    assert "for attempt in 1 2" in workflow
    assert "sleep 30" in workflow
