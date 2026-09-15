import json
import subprocess

import pytest

from test_pipeline_runtime_contract import module


@pytest.mark.parametrize("resolution,width,height,accepted", [
    ("768P", 768, 1344, True),
    ("768p竖", 768, 1344, True),
    ("768P", 768, 1365, True),
    ("2K", 1440, 2560, True),
    ("2K", 768, 1344, False),
    ("768P", 1344, 768, False),
    ("768P", 768, 1200, False),
])
def test_video_resolution_compatibility(tmp_path, monkeypatch, resolution, width, height, accepted):
    runner = module()
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"offline-media-fixture")
    calls = []

    def run(args, **kwargs):
        calls.append(args[0])
        probe = {"streams": [{"codec_type": "video", "width": width, "height": height},
                             {"codec_type": "audio"}], "format": {"duration": "15"}}
        return subprocess.CompletedProcess(args, 0, json.dumps(probe), "")

    monkeypatch.setattr(runner.subprocess, "run", run)
    if accepted:
        result = runner.validate_video_file(candidate, resolution)
        assert (result["width"], result["height"]) == (width, height)
        assert result["full_decode"] is True
        assert calls == ["ffprobe", "ffmpeg"]
    else:
        with pytest.raises(ValueError, match="视频方向或分辨率"):
            runner.validate_video_file(candidate, resolution)
