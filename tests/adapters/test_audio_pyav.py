import math
from pathlib import Path

import av
import numpy as np
import pytest

from dehydrater.adapters.audio_pyav import PyAVAudioExtractor


def _write_tone(path: Path, seconds: float, codec: str = "aac", rate: int = 44_100) -> None:
    """生成一段立体声正弦波，容器由扩展名决定，模拟课堂录像或录音的音轨。"""
    t = np.arange(int(seconds * rate)) / rate
    wave = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    with av.open(path, "w") as container:
        stream = container.add_stream(codec, rate=rate, layout="stereo")
        assert isinstance(stream, av.AudioStream)
        frame = av.AudioFrame.from_ndarray(np.stack([wave, wave]), format="fltp", layout="stereo")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


@pytest.mark.parametrize(
    ("name", "codec"),
    [("lecture.mp4", "aac"), ("lecture.m4a", "aac"), ("lecture.wav", "pcm_s16le")],
)
def test_extracts_mono_16k_mp3(tmp_path: Path, name: str, codec: str) -> None:
    recording = tmp_path / name
    _write_tone(recording, seconds=2.0, codec=codec)
    dest = tmp_path / "out" / "audio.mp3"

    extracted = PyAVAudioExtractor().extract(recording, dest)

    assert extracted.duration == pytest.approx(2.0, abs=0.1)
    with av.open(dest) as result:
        stream = result.streams.audio[0]
        assert result.format.name == "mp3"
        assert stream.codec_context.channels == 1
        assert stream.codec_context.sample_rate == 16_000
