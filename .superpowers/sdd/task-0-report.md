# Task 0 report: reconcile preserved changes with the baseline suite

## Scope and starting point

- Working branch baseline: `afc470a chore: preserve existing product video pipeline changes`.
- Initial command: `python -m pytest tests/test_portable_skill_package.py -q`.
- Initial result: `13 failed, 55 passed in 5.16s`.
- No Task 1–10 automation production files were added.

## Failure classification

| Original failure | Classification | Resolution |
| --- | --- | --- |
| Skill entrypoint wording | Stale assertion | Assert the explicit-trigger description now documented in `SKILL.md`. |
| Image-generation routing wording | Stale assertion | Assert the current Codex-only routing exception instead of the obsolete native-image prohibition. |
| First-level and work-file documentation | Stale assertion | Assert the title-derived final-video contract, not the retired `--title-file` cover rendering flow. |
| Item organization and legacy video | Real regression plus stale expectations | Prevent a source already archived by the output audit from being moved a second time; assert the current archival location for stray videos. |
| Duplicate item organization root cleanliness | Real regression | A missing title without any video is now recorded as a missing output, not an audit error. |
| Batch organization root cleanliness | Real regression | Same missing-title audit correction as the duplicate-item case. |
| `classify_legacy_entry` call | Stale assertion | Supply both `item_dir` and `path`, matching the preserved signature. |
| `review-output` video promotion | Stale assertion | Create and approve a title candidate before promoting the video, then assert the title-derived filename. |
| Organize CLI audit-error reporting | Real regression plus stale physical path | Check a title-derived video path and report a directory-shaped stray video as a JSON audit error rather than raising during hashing. |
| AutoDL dry-run payload fields | Stale assertion | Assert API `ref_image_0`/`ref_image_1` mapping and absence of local semantic fields in the submitted payload. |
| Fixed video workflow documentation | Stale assertion | Assert `minimax_h3_lightx2v_v5_15s`. |
| First/last-frame workflow documentation | Stale assertion | Assert `minimax_h3_lightx2v_v5_15s`. |
| Review report video promotion | Stale assertion | Approve the title candidate before promoting, and use the title-derived root video file. |

## Root cause and minimal implementation fix

The preserved title-derived video naming made `deliverable_root_path(..., "视频.mp4")` raise when an early-stage item had no accepted title. The audit then treated ordinary incomplete items as erroneous. In addition, the audit could move an unapproved stray `.mp4` before the organizer executed its previously calculated move plan, causing a second `shutil.move` attempt on Windows.

`workflow_cli.py` now:

1. Treats a title-derived video path that cannot yet be calculated as a missing video rather than an audit error.
2. Records a non-file stray `.mp4` as an audit error without attempting to hash it.
3. Removes audit-moved sources from the organizer's precomputed plan before performing file moves.

These changes preserve immutable approval history, title-based final naming, safety audits, and duplicate-submit protections.

## TDD evidence

### RED

After aligning stale test expectations with the preserved contract, the focused regression command was:

```powershell
python -m pytest tests/test_portable_skill_package.py -q -k "organize_item_dir_keeps_only_deliverables_and_categorizes_work_files or organize_item_dir_preserves_identical_file_and_directory_duplicates or batch_organizer_only_visits_video_items_and_preserves_batch_files"
```

Result before the implementation correction: `3 failed, 65 deselected`. The failures demonstrated the second move of `视频_V02.mp4` after auditing and the incorrect `root_clean=False` result for items with no accepted title/video.

### GREEN

After the minimal implementation correction, the focused command was:

```powershell
python -m pytest tests/test_portable_skill_package.py -q -k "organize_item_dir_keeps_only_deliverables_and_categorizes_work_files or organize_item_dir_preserves_identical_file_and_directory_duplicates or batch_organizer_only_visits_video_items_and_preserves_batch_files or organize_cli_propagates"
```

Result: `4 passed, 64 deselected in 0.27s`.

The updated preserved-contract assertions also passed in a focused run: `9 passed, 59 deselected in 0.19s`.

## Final verification

```powershell
python -m pytest tests/test_portable_skill_package.py -q
# 68 passed in 4.38s

python skill-package/product-video-pipeline/scripts/self_test.py
# product-video-pipeline 自检通过（无网络、无付费调用）
```

`git diff --check` completed without whitespace errors. The diff is restricted to the baseline test and the directly implicated workflow script; no low-cost automation production files were introduced.
