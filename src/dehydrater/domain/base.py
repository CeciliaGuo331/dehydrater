from pydantic import BaseModel, ConfigDict

type Seconds = float
"""视频内的时间点，单位为秒。"""


class DomainModel(BaseModel):
    """所有领域模型的基类：不可变，且拒绝未知字段，以便尽早发现数据格式漂移。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
