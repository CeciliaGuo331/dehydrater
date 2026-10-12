from pathlib import Path

from dehydrater.domain.transcript import Transcript
from dehydrater.ports import Fingerprint, TranscriptionHints


class VolcengineTranscriber:
    """豆包语音「大模型录音文件识别」，提交任务后轮询结果。

    接口文档：docs/豆包语音_录音文件识别标准版HTTP_*.pdf
    """

    def __init__(self, *, api_key: str, resource_id: str) -> None:
        self._api_key = api_key
        self._resource_id = resource_id

    def fingerprint(self) -> Fingerprint:
        return {"service": "volcengine-auc", "resource_id": self._resource_id}

    async def transcribe(self, audio: Path, hints: TranscriptionHints) -> Transcript:
        # 标准版只接受音频 URL，不能直接上传本地文件。上传方案待定，见 S1。
        raise NotImplementedError("计划在 S1 实现")
