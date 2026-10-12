import logging
from datetime import datetime
from pathlib import Path

import av
from av.error import FFmpegError

from dehydrater.ports import ExtractedAudio, Fingerprint, MediaInfo, NotAMediaFileError

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16_000
_BIT_RATE = 32_000
_CODEC = "libmp3lame"
_FORMAT = "mp3"


class PyAVAudioExtractor:
    """把录像或录音的音轨统一转成 16kHz 单声道 MP3。90 分钟约 22MB，足够语音识别使用。

    选 MP3 是因为各家 ASR 普遍支持，火山极速版和方舟都不接受 Opus。
    """

    def fingerprint(self) -> Fingerprint:
        return {"codec": _CODEC, "sample_rate": _SAMPLE_RATE, "bit_rate": _BIT_RATE}

    def probe(self, recording: Path) -> MediaInfo:
        try:
            with av.open(recording) as container:
                if not container.streams.audio:
                    raise NotAMediaFileError(f"{recording.name} 中没有音轨")
                duration = (container.duration or 0) / av.time_base
                created = container.metadata.get("creation_time")
        except FFmpegError as error:
            raise NotAMediaFileError(f"{recording.name} 不是可识别的音视频文件") from error
        return MediaInfo(duration=duration, recorded_at=_parse_time(created))

    def extract(self, recording: Path, dest: Path) -> ExtractedAudio:
        dest.parent.mkdir(parents=True, exist_ok=True)
        samples = 0
        with av.open(recording) as source, av.open(dest, "w", format=_FORMAT) as sink:
            if not source.streams.audio:
                raise NotAMediaFileError(f"{recording.name} 中没有音轨")
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
        logger.info(
            "提取音频：%s → %s，时长 %.0f 秒，%.1f MB",
            recording.name,
            dest,
            samples / _SAMPLE_RATE,
            dest.stat().st_size / 1e6,
        )
        return ExtractedAudio(duration=samples / _SAMPLE_RATE)


def _parse_time(value: str | None) -> datetime | None:
    """元数据中的时间形如 2026-09-30T02:15:00.000000Z。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
