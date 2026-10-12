from collections.abc import Sequence

from dehydrater.domain.transcript import TranscriptSegment


def chunk_segments(segments: Sequence[TranscriptSegment], max_chars: int) -> list[range]:
    """按字数把分句切成若干块，只在分句边界切开。返回每块对应的下标区间。

    单个分句超过 max_chars 时独占一块，不会被截断。
    """
    chunks: list[range] = []
    start = 0
    size = 0
    for index, segment in enumerate(segments):
        if size and size + len(segment.text) > max_chars:
            chunks.append(range(start, index))
            start, size = index, 0
        size += len(segment.text)
    if start < len(segments):
        chunks.append(range(start, len(segments)))
    return chunks
