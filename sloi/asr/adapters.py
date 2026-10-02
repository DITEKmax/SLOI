from __future__ import annotations

import ctypes
import importlib.metadata
import os
from pathlib import Path
from typing import Any

import numpy as np

from sloi.domain import Recognition


_DLL_HANDLES: list[Any] = []


def preload_cuda(directories: list[str]) -> None:
    if os.name != "nt":
        return
    for raw in directories:
        directory = Path(raw)
        if not directory.is_dir():
            continue
        _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
        for name in ("nvJitLink_120_0.dll", "cudart64_12.dll", "cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"):
            path = directory / name
            if path.is_file():
                try:
                    _DLL_HANDLES.append(ctypes.WinDLL(str(path)))
                except OSError:
                    pass


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


class OnnxAdapter:
    def __init__(self, spec: dict[str, Any]):
        import onnxruntime as ort
        import onnx_asr
        self.spec = spec
        if hasattr(ort, "preload_dlls"):
            for directory in spec.get("cuda_dll_directories", []):
                ort.preload_dlls(directory=directory)
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("CUDAExecutionProvider unavailable; CPU fallback is disabled")
        options = ort.SessionOptions()
        options.intra_op_num_threads = spec.get("cpu_threads", 4)
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        provider = ("CUDAExecutionProvider", {
            "device_id": spec.get("gpu_index", 0),
            "gpu_mem_limit": int(spec.get("gpu_memory_limit_mb", 3000)) * 1024**2,
            "arena_extend_strategy": "kSameAsRequested",
            "cudnn_conv_algo_search": "DEFAULT",
            "cudnn_conv_use_max_workspace": "0",
        })
        self.model = onnx_asr.load_model(spec["loader_name"], spec["path"], quantization=spec.get("quantization"), sess_options=options, providers=[provider], preprocessor_config={"providers": ["CPUExecutionProvider"], "use_numpy_preprocessors": True, "max_concurrent_workers": 1}, resampler_config={"providers": ["CPUExecutionProvider"]})
        self.sessions = self._sessions(self.model, ort.InferenceSession)
        if not any("CUDAExecutionProvider" in s.get_providers() for s in self.sessions):
            raise RuntimeError("No ASR session uses CUDA. Refusing silent CPU fallback.")
        for session in self.sessions:
            session.disable_fallback()

    @staticmethod
    def _sessions(value: Any, session_type: type) -> list[Any]:
        found, seen = [], set()
        def visit(item: Any, depth: int) -> None:
            if depth > 7 or id(item) in seen:
                return
            seen.add(id(item))
            if isinstance(item, session_type):
                found.append(item)
            elif isinstance(item, dict):
                for v in item.values():
                    visit(v, depth + 1)
            elif isinstance(item, (list, tuple)):
                for v in item:
                    visit(v, depth + 1)
            elif not isinstance(item, type):
                if hasattr(item, "__dict__"):
                    visit(vars(item), depth + 1)
                for cls in type(item).__mro__:
                    slots = getattr(cls, "__slots__", ())
                    for slot in (slots,) if isinstance(slots, str) else slots:
                        if hasattr(item, slot):
                            visit(getattr(item, slot), depth + 1)
        visit(value, 0)
        return found

    def recognize(self, waves: list[np.ndarray], language: str) -> list[Recognition]:
        texts = self.model.recognize(waves, sample_rate=16000)
        if isinstance(texts, str):
            texts = [texts]
        is_russian = self.spec["model_id"] == "gigaam"
        return [Recognition(text=str(text), language="ru" if is_russian else None, language_origin="model_capability" if is_russian else None) for text in texts]

    def metadata(self) -> dict[str, Any]:
        return {"runtime": "onnx-asr", "runtime_version": package_version("onnx-asr"), "onnxruntime_version": package_version("onnxruntime-gpu"), "gpu_execution": "CUDAExecutionProvider", "compute_type": self.spec["compute_type"], "quantization": self.spec.get("quantization"), "language_hint_supported": False}


class WhisperAdapter:
    def __init__(self, spec: dict[str, Any]):
        import ctranslate2
        from faster_whisper import WhisperModel
        if ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError("CTranslate2 cannot access CUDA. CPU fallback is disabled.")
        self.spec = spec
        self.model = WhisperModel(spec["path"], device="cuda", device_index=spec.get("gpu_index", 0), compute_type=spec["compute_type"], cpu_threads=spec.get("cpu_threads", 4), num_workers=1, local_files_only=True)

    def recognize(self, waves: list[np.ndarray], language: str) -> list[Recognition]:
        results = []
        for wave in waves:
            segments, info = self.model.transcribe(wave, language=None if language == "auto" else language, task="transcribe", beam_size=self.spec.get("beam_size", 5), vad_filter=False, condition_on_previous_text=False, word_timestamps=False, temperature=0.0, hotwords=self.spec.get("hotwords"))
            text = " ".join(s.text.strip() for s in segments).strip()
            results.append(Recognition(text=text, language=info.language, language_origin="detected" if language == "auto" else "hint"))
        return results

    def metadata(self) -> dict[str, Any]:
        return {"runtime": "faster-whisper", "runtime_version": package_version("faster-whisper"), "ctranslate2_version": package_version("ctranslate2"), "gpu_execution": "cuda", "compute_type": self.spec["compute_type"], "language_hint_supported": True, "batch_execution": "sequential", "beam_size": self.spec.get("beam_size", 5)}


def parse_qwen_raw(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if "<asr_text>" not in raw:
        return {"language": None, "transcription": raw}
    prefix, text = raw.split("<asr_text>", 1)
    prefix = prefix.strip()
    language = prefix[len("language "):].strip() if prefix.lower().startswith("language ") else None
    return {"language": None if language and language.lower() == "none" else language, "transcription": text.strip()}


class QwenAdapter:
    def __init__(self, spec: dict[str, Any]):
        import torch
        from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration
        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch cannot access CUDA. CPU fallback is disabled.")
        self.spec, self.torch = spec, torch
        torch.set_num_threads(spec.get("cpu_threads", 4))
        self.device = torch.device(f"cuda:{spec.get('gpu_index', 0)}")
        self.dtype = torch.bfloat16 if spec.get("compute_type") == "bfloat16" else torch.float16
        self.processor = AutoProcessor.from_pretrained(spec["path"], local_files_only=True, trust_remote_code=False)
        self.model = Qwen3ASRForConditionalGeneration.from_pretrained(spec["path"], dtype=self.dtype, attn_implementation=spec.get("attention", "sdpa"), local_files_only=True, trust_remote_code=False).to(self.device).eval()

    def recognize(self, waves: list[np.ndarray], language: str) -> list[Recognition]:
        kwargs: dict[str, Any] = {"audio": waves, "sampling_rate": 16000, "return_tensors": "pt", "padding": True}
        if language != "auto":
            kwargs["language"] = language
        if self.spec.get("context"):
            kwargs["prompt"] = self.spec["context"]
        inputs = self.processor.apply_transcription_request(**kwargs).to(self.device, self.dtype)
        max_tokens = self.spec.get("max_new_tokens", 512)
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
        generated = output[:, inputs["input_ids"].shape[1]:]
        decoded = self.processor.decode(generated, return_format="raw", skip_special_tokens=True)
        if isinstance(decoded, str):
            decoded = [decoded]
        parsed = [parse_qwen_raw(text) for text in decoded]
        results = []
        for index, item in enumerate(parsed):
            warnings = []
            if generated.shape[1] >= max_tokens:
                eos = self.model.generation_config.eos_token_id
                eos_values = eos if isinstance(eos, list) else [eos]
                sequence = generated[index].tolist()
                if not any(token in sequence for token in eos_values if token is not None):
                    warnings.append("GENERATION_TOKEN_LIMIT: сегмент достиг лимита токенов; возможен обрыв текста.")
            detected = item.get("language")
            if detected:
                detected = {"Russian": "ru", "English": "en"}.get(detected, detected)
            results.append(Recognition(text=item.get("transcription", ""), language=detected if language == "auto" else language, language_origin="detected" if language == "auto" and detected else ("hint" if language != "auto" else None), warnings=warnings))
        return results

    def metadata(self) -> dict[str, Any]:
        return {"runtime": "transformers-qwen3-asr", "runtime_version": package_version("transformers"), "torch_version": self.torch.__version__, "cuda_runtime": self.torch.version.cuda, "gpu_execution": str(self.device), "compute_type": str(self.dtype).removeprefix("torch."), "language_hint_supported": True, "max_new_tokens": self.spec.get("max_new_tokens", 512), "repetition_postprocessing": False}


def load_adapter(spec: dict[str, Any]) -> Any:
    preload_cuda(spec.get("cuda_dll_directories", []))
    adapters = {"onnx": OnnxAdapter, "faster-whisper": WhisperAdapter, "qwen-transformers": QwenAdapter}
    if spec["runtime"] not in adapters:
        raise ValueError("Unsupported ASR runtime")
    return adapters[spec["runtime"]](spec)
