# Task 5 Report

## Result

Implemented deterministic AutoDL submission, resumable polling, atomic download handoff, and local ffprobe validation without consuming model-call counters. Added fail-closed V01/V02/V03 paid-submit authorization and V01 submission-identity archival before a V02 rerun.

## Commit

- `f336960 feat: run video submit polling and download without model turns`

## Verification

- RED observed: the required focused command selected two tests and both failed because `_submit_item` did not exist.
- Expanded RED observed: 10 focused orchestration, authorization, ffprobe, public-status, and rerun tests failed for the expected missing behavior.
- Focused GREEN: 10/10 focused Task 5 tests passed.
- AutoDL/rerun regression selection: 10/10 tests passed, including existing dry-run and task-ID parsing coverage.
- Full suite: `python -m pytest` — `90 passed in 5.73s`.
- Offline package self-test: `python scripts/self_test.py` from the skill-package root — exit code 0.
- No live or paid network request was made. The resume test stubs polling/download/validation, and the new-submit test explicitly supplies an authorized V01 state before stubbing every external boundary.

## Self-review

- A persisted `task_id` bypasses submission and resumes polling; a persisted `request_hash` without a task ID fails closed instead of paying twice.
- V01 requires both an approved budget and an estimated total no greater than that budget. V02 requires authorization keyed to the specific video, and any V03 attempt is rejected.
- `start_rerun()` archives the V01 task ID, request ID, request hash, and estimated cost under `submission_history` before clearing the active submission identity and writing V02 state.
- Poll, download, and ffprobe validation never call `consume_model_call()` and return compact orchestration results.
- ffprobe is invoked once with a subprocess argument list; validation enforces a non-empty decodable file, video and audio streams, 13–17 second duration, portrait orientation, and the exact selected resolution.
- `git show --check` reported no whitespace errors for the implementation commit.

## Concerns

No implementation concern within Task 5 scope. Live AutoDL schema and media behavior remain intentionally untested because this task prohibited live/paid network calls.

## Review Follow-up — 2026-09-08

### Findings fixed

- Paid submission now computes a deterministic preview hash, atomically persists `submission_pending` plus that hash before POST, then atomically persists any returned task identity before the broader task record is updated.
- Provider timeout, missing task ID, hash mismatch, and task-recording failure all transition the runner to `BLOCKED` and return `RECONCILIATION_REQUIRED`. Any later invocation with an unresolved marker returns the same blocked result without entering the submit adapter.
- Successful recording clears `submission_pending`; ordinary persisted task IDs still resume polling without another submission.
- Video validation now resolves the expected resolution from the actual submission payload first, then `启动确认单.json`, before using the legacy task-info/default fallback. A 2K batch therefore reaches the validator as `2K`.
- Paid authorization accepts only retry count 0 or 1. V01 budget values and per-video V02 authorization values must parse as finite positive decimals; negative/unknown versions and empty, zero, negative, NaN, infinite, or invalid authorization amounts fail closed.

### RED/GREEN evidence

- Review RED: `python -m pytest tests/test_portable_skill_package.py -k "ambiguous_paid_submit or existing_request_hash or invalid_retry_count or authorization_amount or confirmation_resolution" -v` — 13 failed and 1 pre-existing V03 case passed, with failures matching the three review findings.
- Successful-marker RED: the focused successful-submit test failed because `submission_pending` was absent after task recording.
- Focused GREEN: the expanded selection covering pre-POST persistence, provider/recording ambiguity, duplicate-submit prevention, strict authorization, 2K resolution, rerun behavior, and unchanged model counters — 19 passed.
- Task 5 relevant regression selection — 20 passed.
- Full suite: `python -m pytest` — 104 passed in 6.09s.
- Offline package self-test: `python scripts/self_test.py` — exit code 0.
- All submission boundaries remained stubbed; no live or paid network request was made.

### Follow-up concerns

None within scope. Resolving a `RECONCILIATION_REQUIRED` marker remains an explicit manual/provider-reconciliation operation; automatic clearing would reintroduce double-charge risk.
