"""Tests for scripts/recommend_models.py.

The script is deliberately outside the Django app (it must run before the
project is installed), so it is loaded by path rather than imported.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'recommend_models.py'


def _load():
    spec = importlib.util.spec_from_file_location('recommend_models', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['recommend_models'] = module
    spec.loader.exec_module(module)
    return module


rm = _load()


def _hw(ram_gb, vram_gb=None):
    return rm.Hardware(
        total_ram_gb=ram_gb,
        cpu_cores=8,
        gpu_name='GPU' if vram_gb else None,
        vram_gb=vram_gb,
    )


class TestMemoryBudget:
    def test_gpu_budget_uses_vram_not_ram(self):
        """A machine with lots of RAM but a small GPU is bound by VRAM."""
        assert rm.memory_budget_gb(_hw(ram_gb=64, vram_gb=8)) == pytest.approx(7.0)

    def test_cpu_budget_is_capped(self):
        """Extra RAM buys nothing on CPU: generation speed binds first."""
        assert rm.memory_budget_gb(_hw(ram_gb=128)) == rm.CPU_BUDGET_CAP_GB

    def test_cpu_budget_reserves_room_for_the_stack(self):
        assert rm.memory_budget_gb(_hw(ram_gb=8)) == pytest.approx(8 - rm.STACK_OVERHEAD_GB)

    def test_budget_never_negative(self):
        assert rm.memory_budget_gb(_hw(ram_gb=2)) == 0.0


class TestPick:
    def test_picks_largest_model_that_fits(self):
        assert rm.pick(rm.LLM_MODELS, budget_gb=6.0, runtime_gb=rm.LLM_RUNTIME_GB).name == 'gemma3:4b'

    def test_gpu_machine_gets_a_bigger_model_than_cpu(self):
        cpu = rm.pick(rm.LLM_MODELS, rm.memory_budget_gb(_hw(16)), rm.LLM_RUNTIME_GB)
        gpu = rm.pick(rm.LLM_MODELS, rm.memory_budget_gb(_hw(16, vram_gb=16)), rm.LLM_RUNTIME_GB)
        assert cpu.size_gb < gpu.size_gb

    def test_falls_back_to_smallest_when_nothing_fits(self):
        assert rm.pick(rm.LLM_MODELS, budget_gb=0.0, runtime_gb=rm.LLM_RUNTIME_GB) is rm.LLM_MODELS[0]

    def test_target_16gb_cpu_machine_matches_shipped_defaults(self):
        """The README and .env.example promise these two on the 16 GB target."""
        budget = rm.memory_budget_gb(_hw(ram_gb=16))
        assert rm.pick(rm.LLM_MODELS, budget, rm.LLM_RUNTIME_GB).name == 'gemma3:4b'
        assert rm.pick(rm.EMBED_MODELS, budget, rm.EMBED_RUNTIME_GB).name == 'bge-m3'


class TestInstalledModels:
    def test_non_http_url_is_refused(self, tmp_path):
        """A file:// OLLAMA_URL must not turn into a local file read."""
        assert rm.installed_models(f'file://{tmp_path}') is None

    def test_unreachable_ollama_returns_none(self):
        assert rm.installed_models('http://127.0.0.1:1') is None
