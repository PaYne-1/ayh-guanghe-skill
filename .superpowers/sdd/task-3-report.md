# Task 3 Report

## Outcome

Implemented deterministic GPT Web image normalization and automatic promotion for
`分镜图.png`, `尾帧图.png`, and `封面图.png`.

The runner now verifies non-empty locally decodable images, requires an exact 9:16
source ratio without cropping or stretching, writes a deterministic RGB PNG at
`2160×3840` by default, records its SHA-256, stores the candidate under the task's
`_工作文件/生成过程` directory, and promotes it through the existing immutable
workflow approval APIs using `batch-auto-authorization`. Tail-frame acceptance
requires an already promoted storyboard with a distinct normalized hash.

## RED Evidence

Command:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "web_image or storyboard_and_last_frame" -v
```

Result:

- 3 failed, 73 deselected
- Failures were the expected `AttributeError` errors for the two undefined image functions.

## Focused GREEN Evidence

Command:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "web_image or storyboard_and_last_frame or approval_events or artifact_decision" -v
```

Result:

- 8 passed, 68 deselected

## Full Suite

Command:

```powershell
python -m pytest -v
```

Result:

- 76 passed

## Self-Review

- No external-action CLI or network behavior was added.
- Existing `workflow_cli.record_artifact_decision()` and
  `workflow_cli.promote_approved_artifact()` remain the only approval/promotion path.
- The approval-log assertion follows the existing `{"events": [...]}` log schema.
- `git diff --check` reports only the repository's normal LF/CRLF normalization warning.

## Follow-up Review Fix: Symmetric Frame-Hash Guard

### RED Evidence

Added `test_storyboard_reacceptance_cannot_match_promoted_last_frame`, covering
storyboard A → tail B → storyboard B. Before the fix:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "storyboard_reacceptance_cannot_match_promoted_last_frame" -v
```

Result: 1 failed, 76 deselected (`DID NOT RAISE`). The storyboard branch lacked a
check against the already promoted tail frame, so it could overwrite the storyboard
with the tail hash.

### GREEN Evidence

Added the symmetric pre-event guard for `分镜图.png`. The regression now passes and
asserts the existing promoted storyboard bytes and approval log are unchanged:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "storyboard_reacceptance_cannot_match_promoted_last_frame" -v
```

Result: 1 passed, 76 deselected.

Task 3-focused verification:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "web_image or storyboard_and_last_frame or storyboard_reacceptance_cannot_match_promoted_last_frame or approval_events or artifact_decision" -v
```

Result: 9 passed, 68 deselected.

Fresh full portable-package suite:

```powershell
python -m pytest tests/test_portable_skill_package.py -q
```

Result: 77 passed.
