# Deployment Contract

## Railway build and process

Railway uses the repository-root `Dockerfile`. The production image installs
only `requirements.txt`; optional emotion tooling and test dependencies live in
`requirements-dev.txt`.

The container starts one process:

```text
python -m src.main
```

The process listens on Railway's injected `PORT`. `railway.json` configures:

- Dockerfile builds;
- deployment readiness checks on `/ready`;
- a 120-second startup window;
- restart on failure with at most 10 retries.

Railway sends deployment health checks with the host
`healthcheck.railway.app`. That host is accepted only for `/health` and
`/ready`; it cannot
reach the authenticated dashboard.

## Runtime data

Production conversation state must use the managed PostgreSQL
`DATABASE_URL`. The `/data` volume is reserved for operator-edited persona and
brand-reference files:

```text
/data/config/creators/{creator_id}.yaml
/data/config/brand_bible.md
```

The image intentionally runs as root because Railway mounts volumes as root.
Changing to a non-root image requires setting and verifying Railway's volume
UID configuration first.

## Local commands

Install the production dependency set:

```text
python -m pip install -r requirements.txt
```

Install the full test and optional emotion-tool set:

```text
python -m pip install -r requirements-dev.txt
```

Run the service:

```text
python -m src.main
```

Before a production rollout, verify the image boots with production
dependencies only and that `/health` and `/ready` return HTTP 200.
