from __future__ import annotations

import asyncio

import pytest

from conn import evals
from conn.config import PROJECT_ROOT, load_config

# Every harness eval runs here, so a harness regression fails the normal test
# run instead of waiting for someone to run `python -m conn --eval`. Cases load
# the repo config.toml because some expectations (the hotkey allowlist) live
# there; data_dir moves to tmp so nothing lands in data/.
CASES = evals.load_eval_cases()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_harness_eval_case(case, tmp_path):
    cfg = load_config(PROJECT_ROOT / "config.toml")
    cfg.data_dir = tmp_path / "data"

    result = asyncio.run(evals._run_case(case, cfg))

    assert result["passed"], result["failures"]


def test_every_eval_case_is_collected():
    assert len(CASES) == 14
