from pathlib import Path

import av

from dehydrater.ports import ExtractedAudio, Fingerprint

_SAMPLE_RATE = 16_000
_BIT_RATE = 24_000
_CODEC = "libopus"


class NoAudioStreamError(Exception):
    pass


class PyAVAudioExtractor:
    """把视频音轨转成 16kHz 单声道 Ogg Opus。90 分钟约 16MB，足够语音识别使用。"""

    def fingerprint(self) -> Fingerprint:
        return {"codec": _CODEC, "sample_rate": _SAMPLE_RATE, "bit_rate": _BIT_RATE}

    def extract(self, video: Path, dest: Path) -> ExtractedAudio:
        dest.parent.mkdir(parents=True, exist_ok=True)
        samples = 0
        with av.open(video) as source, av.open(dest, "w", format="ogg") as sink:
            if not source.streams.audio:
                raise NoAudioStreamError(f"{video} 中没有音轨")
            encoder = sink.add_stream(_CODEC, rate=_SAMPLE_RATE, layout="mono")
            encoder.bit_rate = _BIT_RATE
            resampler = av.AudioResampler(format="s16", layout="mono", rate=_SAMPLE_RATE)

            def encode(frame: av.AudioFrame | None) -> None:
                for packet in encoder.encode(frame):
                    sink.mux(packet)

            for frame in source.decode(source.streams.audio[0]):
                for resampled in resampler.resample(frame):
                    samples += resampled.samples
                    encode(resampled)
            for resampled in resampler.resample(None):
                samples += resampled.samples
                encode(resampled)
            encode(None)
        return ExtractedAudio(duration=samples / _SAMPLE_RATE)
