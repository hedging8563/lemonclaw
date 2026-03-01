"""Shared utilities for channel implementations."""


def split_message(content: str, max_len: int) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks."""
    if max_len <= 0:
        raise ValueError(f"max_len must be positive, got {max_len}")
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks
