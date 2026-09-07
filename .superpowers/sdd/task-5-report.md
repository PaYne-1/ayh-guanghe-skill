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
