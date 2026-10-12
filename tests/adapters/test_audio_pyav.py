import math
from pathlib import Path

import av
import numpy as np
import pytest

from dehydrater.adapters.audio_pyav import PyAVAudioExtractor


def _write_tone(path: Path, seconds: float, rate: int = 44_100) -> None:
    """生成一段立体声正弦波 MP4，模拟课堂录像的音轨。"""
    t = np.arange(int(seconds * rate)) / rate
    wave = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    with av.open(path, "w") as container:
        stream = container.add_stream("aac", rate=rate, layout="stereo")
        frame = av.AudioFrame.from_ndarray(np.stack([wave, wave]), format="fltp", layout="stereo")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def test_extracts_mono_16k_opus(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    _write_tone(video, seconds=2.0)
    dest = tmp_path / "out" / "audio.ogg"

    extracted = PyAVAudioExtractor().extract(video, dest)

    assert extracted.duration == pytest.approx(2.0, abs=0.1)
    with av.open(dest) as result:
        stream = result.streams.audio[0]
        assert stream.codec_context.name == "opus"
        assert stream.codec_context.channels == 1
