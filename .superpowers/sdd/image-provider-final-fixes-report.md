# Image provider final fixes report

## Scope

Applied only the final-review source, documentation, and regression-test fixes. No release ZIP was built, edited, staged, or packaged.

## RED evidence

New focused tests were written before production or documentation changes and run with:

```powershell
python -m pytest tests/test_image_provider_selection.py -q -k "named_api_credential or later_api_config_change or old_runner_state_without_image_api_ledger or generic_reservation_rejects or contradictory_submission_state or gpt_web_failure_replays"
python -m pytest tests/test_portable_skill_package.py -q -k "required_image_provider_and_failure_settlement_contract"
```

Observed expected failures:

- `test_generic_reservation_rejects_third_party_image_category`: `_reserve_action(..., "third_party_api_image")` did not raise.
- `test_third_party_failure_rejects_same_reason_with_contradictory_submission_state`: a second failure receipt with the same reason but `unknown` after `sent` returned success.
- `test_operator_docs_show_required_image_provider_and_failure_settlement_contract`: the required `gpt_web` init example and failure-settlement contract were absent.

The other new tests passed on the baseline, recording existing behavior for named API credentials, approved-manifest mutation protection, and missing-ledger backward compatibility.

## GREEN evidence

After the minimal implementation and documentation edits, the same focused commands passed:

- provider/runtime focus: `6 passed, 27 deselected`
- documentation focus: `1 passed, 127 deselected`

Final requested provider/runtime/portable coverage:

```powershell
python -m pytest tests/test_image_provider_selection.py -q
python -m pytest tests/test_pipeline_runtime_contract.py -q -k "not release_source_parity_and_security and not self_test and not git_diff"
python -m pytest tests/test_pipeline_mixed_batch.py -q -k "passed_sibling or diagnostic_receipt or repaired_environment or prepost_sibling"
python -m pytest tests/test_pipeline_mixed_batch.py -q -k "malformed_content or failed_feedback"
python -m pytest tests/test_pipeline_mixed_batch.py -q -k "default_review_renderer or fabricated_human_gate or final_completion or done_response"
python -m pytest tests/test_portable_skill_package.py -q -k "not release_source_parity_and_security and not self_test and not git_diff"
git diff --check
```

Results:

- `33 passed` (image-provider selection)
- `29 passed, 1 deselected` (runtime contract; only the excluded historical release parity test)
- `8 passed, 15 deselected`; `9 passed, 14 deselected`; `6 passed, 17 deselected` (all 23 mixed-batch tests)
- `126 passed, 2 deselected` (portable package; only the excluded self-test and git-diff test)
- `git diff --check` clean

## Files changed

- `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
  - reject the generic third-party image category so all paid API image reservations go through the ledger-aware helper;
  - include `submission_state` in third-party `image-failed` receipt digests, while retaining reason-only GPT Web idempotency.
- `skill-package/product-video-pipeline/SKILL.md`
  - add the required `--image-provider gpt_web` init example and third-party non-secret config invocation.
- `skill-package/product-video-pipeline/references/image-generation-routing.md`
  - document `not_sent`, `sent`, and `unknown` failure settlement semantics.
- `tests/test_image_provider_selection.py`
  - add focused ledger-bypass, contradictory-receipt, GPT-Web compatibility, credential, config-mutation, and legacy-state tests.
- `tests/test_portable_skill_package.py`
  - assert the operator-facing CLI and failure-settlement documentation contract.

## Self-review

- Verified third-party contradictory states cannot replay an earlier failure receipt with the same reason.
- Verified GPT Web failure receipts remain idempotent across submission-state values and never create an API ledger row.
- Verified old serialized `RunnerState` without `image_budget_ledger` still loads through the dataclass default.
- Reviewed the diff for secret exposure: documentation names only non-secret JSON fields; no key value is added.
- Confirmed no release archive paths are changed or staged.

## Concerns

- The release archive intentionally remains untouched and its historical parity test is excluded as directed.

## GPT Web legacy receipt compatibility follow-up

### RED evidence

Before changing the digest implementation, added a real persisted-action replay test and ran:

```powershell
python -m pytest tests/test_image_provider_selection.py -q -k "legacy_reason_digest_failure_receipt_replays"
```

Result: `1 failed, 33 deselected`. The test writes a failed `GPT_WEB_IMAGE_REQUIRED` action row with the legacy `hashlib.sha256(reason.encode()).hexdigest()` input digest and invokes the real `image-failed` CLI. The then-current JSON-wrapped digest rejected that replay as a different result.

### GREEN evidence

The runner now uses the exact legacy raw reason SHA-256 for GPT Web and only uses the sorted structured `{reason, submission_state}` digest for third-party API actions. Verification:

```powershell
python -m pytest tests/test_image_provider_selection.py -q -k "legacy_reason_digest_failure_receipt_replays or contradictory_submission_state or gpt_web_failure_replays"
python -m pytest tests/test_image_provider_selection.py -q
python -m pytest tests/test_pipeline_runtime_contract.py -q -k "not release_source_parity_and_security and not self_test and not git_diff"
python skill-package/product-video-pipeline/scripts/self_test.py
git diff --check
```

Results: `3 passed, 31 deselected`; `34 passed`; `29 passed, 1 deselected`; self-test passed without network or charges; `git diff --check` was clean. The third-party contradictory-state regression remains green.

### Follow-up self-review

- GPT Web ignores `submission_state` and exactly preserves its prior persisted-receipt digest format.
- Third-party failure digest still binds both the reason and settlement input, so contradictory replays reject.
- No VERSION, release ZIP, package artifact, or external/paid service changed.
