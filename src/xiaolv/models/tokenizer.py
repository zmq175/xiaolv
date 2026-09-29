"""Load library tokenizers from explicitly provisioned, integrity-checked assets."""

import hashlib
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import tiktoken

_DIGESTS = {
    "cl100k_base": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
    "o200k_base": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
}


def load_tokenizer(name: str) -> tiktoken.Encoding:
    directory = os.environ.get(
        "TIKTOKEN_CACHE_DIR",
        os.environ.get("DATA_GYM_CACHE_DIR", str(Path(tempfile.gettempdir()) / "data-gym-cache")),
    )
    return _load(name, directory)


@lru_cache(maxsize=8)
def _load(name: str, directory: str) -> tiktoken.Encoding:
    url = f"https://openaipublic.blob.core.windows.net/encodings/{name}.tiktoken"
    key = hashlib.sha1(url.encode()).hexdigest()
    try:
        data = (Path(directory) / key).read_bytes() if directory else b""
    except OSError:
        raise ValueError(
            "tokenizer assets missing; provision the configured cache before startup"
        ) from None
    if name not in _DIGESTS or hashlib.sha256(data).hexdigest() != _DIGESTS[name]:
        raise ValueError("tokenizer assets invalid; provision the configured cache before startup")
    return tiktoken.get_encoding(name)
