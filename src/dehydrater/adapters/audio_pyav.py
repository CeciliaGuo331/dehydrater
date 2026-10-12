from pathlib import Path

import av

from dehydrater.ports import ExtractedAudio, Fingerprint

_SAMPLE_RATE = 16_000
_BIT_RATE = 32_000
_CODEC = "libmp3lame"
_FORMAT = "mp3"


class NoAudioStreamError(Exception):
    pass


class PyAVAudioExtractor:
    """把录像或录音的音轨统一转成 16kHz 单声道 MP3。90 分钟约 22MB，足够语音识别使用。

    选 MP3 是因为各家 ASR 普遍支持，火山极速版和方舟都不接受 Opus。
    """

    def fingerprint(self) -> Fingerprint:
        return {"codec": _CODEC, "sample_rate": _SAMPLE_RATE, "bit_rate": _BIT_RATE}

    def extract(self, recording: Path, dest: Path) -> ExtractedAudio:
        dest.parent.mkdir(parents=True, exist_ok=True)
        samples = 0
        with av.open(recording) as source, av.open(dest, "w", format=_FORMAT) as sink:
            if not source.streams.audio:
                raise NoAudioStreamError(f"{recording} 中没有音轨")
            encoder = sink.add_stream(_CODEC, rate=_SAMPLE_RATE, layout="mono")
            encoder.bit_rate = _BIT_RATE
            resampler = av.AudioResampler(format="s16p", layout="mono", rate=_SAMPLE_RATE)

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
