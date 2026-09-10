# Task 1 Report: Deterministic Read-Only Configuration Prompt

## Implemented

- Added `format_configuration_prompt(payload)` to build the exact fixed first-response structure from `format_status(payload)`.
- Added the read-only `prompt` CLI subcommand.
- Made prompt status-read failures return exit code `1` with only `无法读取当前配置状态，永久配置未更改` on stderr.
- Added regression coverage for category labels, masked secrets, the Codex/ChatGPT and MiniMax-H3 clarification, prohibited legacy wording, and non-leaking status-read failures.

## TDD evidence

- RED: `python -m pytest -q -p no:cacheprovider tests/test_api_configuration_prompt.py` failed because `format_configuration_prompt` and `prompt` did not exist.
- GREEN: the same command passed with 2 tests.

## Verification

- `python -m pytest -q -p no:cacheprovider tests/test_api_configuration_prompt.py` — 2 passed.
- `python skill-package/product-video-pipeline/scripts/api_config.py prompt` — emitted all three categories and masked the configured AutoDL secret.
- `git diff --check` — no whitespace errors.

## Self-review

- The prompt branch calls only `status_payload` and `format_configuration_prompt`; it does not call `save_category` or any persistence operation.
- The failure message is constant and does not interpolate the caught exception, preventing the tested `secret-canary` leak.

## Concerns

None for Task 1 scope. The full repository test suite was not used as the acceptance command; the required focused test suite was run.
