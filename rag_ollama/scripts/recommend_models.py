#!/usr/bin/env python3
"""Recommend Ollama models for this machine.

Standalone by design: stdlib only, no Django, no Poetry.  It has to be
runnable *before* the project is set up, because its whole purpose is to
answer "which models should I pull" — and pulling happens first.

    python3 scripts/recommend_models.py
    make models-recommend
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Overhead of everything that is not the LLM: Django + gunicorn threads,
# embedded ChromaDB with its HNSW index, PostgreSQL, the OS itself.
STACK_OVERHEAD_GB = 4.5

# On CPU, generation speed — not memory — is the binding constraint.  A 7B
# model on a laptop CPU answers in minutes, which is not usable interactively,
# so the CPU budget is capped regardless of how much RAM is installed.
CPU_BUDGET_CAP_GB = 6.0

# Weights are only part of the resident cost: the KV cache at
# OLLAMA_CONTEXT_LENGTH=4096 and the runtime add roughly this much on top.
LLM_RUNTIME_GB = 1.5
EMBED_RUNTIME_GB = 0.5


@dataclass(frozen=True)
class Model:
    name: str
    size_gb: float
    note: str


# Ordered small -> large.  The best model is the largest one that fits.
LLM_MODELS: tuple[Model, ...] = (
    Model('gemma3:1b', 0.8, 'аварийный вариант для очень слабой машины'),
    Model('llama3.2:3b', 2.0, 'быстрый, но по-русски заметно слабее gemma3'),
    Model('gemma3:4b', 3.3, 'баланс качества и скорости, хорошо знает русский'),
    Model('qwen2.5:7b', 4.7, 'заметно точнее на длинном контексте'),
    Model('gemma3:12b', 8.2, 'лучшее качество, требует GPU'),
)

EMBED_MODELS: tuple[Model, ...] = (
    Model('embeddinggemma', 0.6, 'мультиязычная, минимальный расход памяти'),
    Model('bge-m3', 1.2, 'мультиязычная, контекст 8192, лучший выбор для русских документов'),
)

# Kept out of the tables above: an English-only embedding model retrieves
# Russian documents poorly, so it is never recommended — only recognised.
LEGACY_EMBED = 'nomic-embed-text'


@dataclass(frozen=True)
class Hardware:
    total_ram_gb: float
    cpu_cores: int
    gpu_name: str | None
    vram_gb: float | None

    @property
    def has_gpu(self) -> bool:
        return self.vram_gb is not None


def detect_ram_gb() -> float:
    """Total physical RAM in GB, 0.0 if it cannot be determined."""
    meminfo = Path('/proc/meminfo')
    if meminfo.is_file():
        match = re.search(r'^MemTotal:\s+(\d+) kB', meminfo.read_text(), re.MULTILINE)
        if match:
            return int(match.group(1)) / 1024 / 1024
    try:  # non-Linux fallback
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024**3
    except (ValueError, OSError, AttributeError):
        return 0.0


def detect_gpu() -> tuple[str | None, float | None]:
    """NVIDIA GPU name and VRAM in GB via nvidia-smi, (None, None) if absent."""
    nvidia_smi = shutil.which('nvidia-smi')
    if nvidia_smi is None:
        return None, None
    try:
        # S603 suppressed: absolute path from shutil.which, argv is a fixed literal.
        out = subprocess.run(  # noqa: S603
            [nvidia_smi, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None, None
    if not out:
        return None, None
    # Multi-GPU: Ollama uses one device per model, so take the largest.
    best_name, best_mib = None, 0.0
    for line in out.splitlines():
        name, _, mib = line.partition(',')
        try:
            value = float(mib.strip())
        except ValueError:
            continue
        if value > best_mib:
            best_name, best_mib = name.strip(), value
    if best_name is None:
        return None, None
    return best_name, best_mib / 1024


def detect_hardware() -> Hardware:
    gpu_name, vram = detect_gpu()
    return Hardware(
        total_ram_gb=detect_ram_gb(),
        cpu_cores=os.cpu_count() or 1,
        gpu_name=gpu_name,
        vram_gb=vram,
    )


def memory_budget_gb(hw: Hardware) -> float:
    """How much memory a model may occupy on this machine."""
    if hw.vram_gb is not None:
        # Leave room for the display and the CUDA context.
        return max(hw.vram_gb - 1.0, 0.0)
    return min(max(hw.total_ram_gb - STACK_OVERHEAD_GB, 0.0), CPU_BUDGET_CAP_GB)


def pick(models: tuple[Model, ...], budget_gb: float, runtime_gb: float) -> Model:
    """Largest model that fits; the smallest one if nothing does."""
    fitting = [m for m in models if m.size_gb + runtime_gb <= budget_gb]
    return fitting[-1] if fitting else models[0]


def read_env_value(key: str) -> str | None:
    """Value of `key` from the environment, falling back to ./.env."""
    if os.environ.get(key):
        return os.environ[key]
    env_file = Path(__file__).resolve().parent.parent / '.env'
    if not env_file.is_file():
        return None
    for raw in env_file.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if line.startswith(f'{key}='):
            return line.split('=', 1)[1].strip().strip('"\'') or None
    return None


def installed_models(ollama_url: str) -> list[str] | None:
    """Model names known to a running Ollama, None if it is unreachable."""
    url = f'{ollama_url.rstrip("/")}/api/tags'
    # OLLAMA_URL comes from .env; without this guard a file:// value would make
    # urlopen read a local file instead of talking to a server.
    if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
        return None
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:  # noqa: S310 — scheme checked above
            payload = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    return [m['name'] for m in payload.get('models', []) if 'name' in m]


def _fits(name: str, installed: list[str] | None) -> str:
    if installed is None:
        return ''
    base = name.split(':')[0]
    for present in installed:
        if present == name or present.split(':')[0] == base:
            return '  [уже загружена]'
    return '  [не загружена]'


def report(hw: Hardware, llm: Model, embed: Model, installed: list[str] | None) -> None:
    budget = memory_budget_gb(hw)

    print('\n=== Железо ===')
    print(f'  RAM           : {hw.total_ram_gb:.1f} ГБ')
    print(f'  CPU           : {hw.cpu_cores} ядер')
    if hw.has_gpu:
        print(f'  GPU           : {hw.gpu_name}, {hw.vram_gb:.1f} ГБ VRAM')
    else:
        print('  GPU           : не найден (nvidia-smi недоступен) -> режим CPU')
    print(f'  Бюджет модели : {budget:.1f} ГБ')
    if not hw.has_gpu and hw.total_ram_gb - STACK_OVERHEAD_GB > CPU_BUDGET_CAP_GB:
        print(
            f'                  (ограничен {CPU_BUDGET_CAP_GB:.0f} ГБ: на CPU упирается'
            ' не в память, а в скорость генерации)'
        )

    print('\n=== Рекомендация ===')
    print(f'  LLM_MODEL={llm.name}'.ljust(38) + f'{llm.size_gb:.1f} ГБ  — {llm.note}' + _fits(llm.name, installed))
    print(
        f'  EMBED_MODEL={embed.name}'.ljust(38)
        + f'{embed.size_gb:.1f} ГБ  — {embed.note}'
        + _fits(embed.name, installed)
    )

    if budget < LLM_MODELS[0].size_gb + LLM_RUNTIME_GB:
        print('\n  ВНИМАНИЕ: на этой машине не помещается даже минимальная модель.')
        print('  Используйте удалённую Ollama: make up-external')

    print('\n=== Что сделать ===')
    print('  1. Впишите в .env:')
    print(f'       LLM_MODEL={llm.name}')
    print(f'       EMBED_MODEL={embed.name}')
    print('  2. Загрузите модели:  make models')

    current_embed = read_env_value('EMBED_MODEL')
    if current_embed and current_embed != embed.name:
        print(f'\n  Сейчас в .env EMBED_MODEL={current_embed}.')
        if current_embed == LEGACY_EMBED:
            print(f'  {LEGACY_EMBED} обучена только на английском — русские документы ищутся заметно хуже.')
        print('  Смена embedding-модели меняет размерность векторов и требует')
        print('  ПОЛНОЙ переиндексации: задайте новое CHROMA_COLLECTION, затем')
        print('  make docker-manage CMD="reindex_documents --status completed"')

    if installed is None:
        print('\n  (Ollama не отвечает — список загруженных моделей проверить не удалось.)')
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true', help='машиночитаемый вывод вместо отчёта')
    args = parser.parse_args()

    hw = detect_hardware()
    budget = memory_budget_gb(hw)
    llm = pick(LLM_MODELS, budget, LLM_RUNTIME_GB)
    embed = pick(EMBED_MODELS, budget, EMBED_RUNTIME_GB)

    if args.json:
        json.dump(
            {
                'total_ram_gb': round(hw.total_ram_gb, 1),
                'cpu_cores': hw.cpu_cores,
                'gpu_name': hw.gpu_name,
                'vram_gb': round(hw.vram_gb, 1) if hw.vram_gb else None,
                'budget_gb': round(budget, 1),
                'llm_model': llm.name,
                'embed_model': embed.name,
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        print()
        return 0

    ollama_url = read_env_value('OLLAMA_URL') or 'http://localhost:11434'
    report(hw, llm, embed, installed_models(ollama_url))
    return 0


if __name__ == '__main__':
    sys.exit(main())
