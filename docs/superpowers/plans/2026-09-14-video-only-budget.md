# Video-only budget implementation plan

Goal: 用户确认预算只统计视频；图片和文本不计入、不拦截，不要求图片单价。

Architecture: Keep video reservation and V02 authorization intact. Optional image prices are informational, with null for unknown costs. Configuration, activation, image reservation, state loading and delivery must all support absent image prices. Warn that provider image/text charges are outside this budget.

Tech stack: Python, pytest, portable skill package.

- [ ] Add parametrized missing/expensive image price tests in tests/test_image_provider_selection.py; run pytest and observe failures.
- [ ] Relax image_api_runtime_config and normalize_image_api_config for absent price; retain validation of supplied prices and secret-field protection.
- [ ] Remove image costs from auto activation and video payment checks; image reservation records optional cost without testing an image budget. Preserve replay protection and state checks.
- [ ] Make delivery represent unknown image cost explicitly and label budget_scope video_only.
- [ ] Update skill budget guidance and regression expectations; run full pytest and package self_test.
- [ ] Publish v1.8.5 source/archive, verify Git remote and sync known installations without changing credentials/data.
