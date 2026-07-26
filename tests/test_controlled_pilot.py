from argparse import Namespace

import pytest

from scripts.controlled_pilot import _validate_environment, parser


FAN_ID = "937641282543562752"


def _environment():
    return {
        "FANSLY_PROVIDER": "fanslyapi",
        "CONTROLLED_LAUNCH": "true",
        "BOT_ENABLED_DEFAULT": "false",
        "FAN_ALLOWLIST": FAN_ID,
    }


def test_controlled_pilot_environment_accepts_exact_single_fan():
    _validate_environment(_environment(), FAN_ID)


def test_controlled_pilot_rejects_enabled_default():
    environment = _environment()
    environment["BOT_ENABLED_DEFAULT"] = "true"

    with pytest.raises(RuntimeError, match="must remain false"):
        _validate_environment(environment, FAN_ID)


def test_controlled_pilot_rejects_multiple_allowlist_entries():
    environment = _environment()
    environment["FAN_ALLOWLIST"] = f"{FAN_ID},other-fan"

    with pytest.raises(RuntimeError, match="only the approved pilot"):
        _validate_environment(environment, FAN_ID)


def test_controlled_pilot_is_dry_run_without_execute_flag():
    args: Namespace = parser().parse_args(
        [
            "--fan-id",
            FAN_ID,
            "--inbound-message-id",
            "message-1",
            "--message",
            "approved reply",
        ]
    )

    assert args.execute is False
