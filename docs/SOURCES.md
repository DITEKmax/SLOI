# Первичные источники и закреплённые артефакты

Проверка документации при подготовке поставки: 28.09.2026. Документация подтверждает API/наличие артефактов, **не доказывает успешный запуск на конкретной GPU**. Версии и commit SHA в `config/models.manifest.json` являются источником для установщика.

## Модели

- GigaAM: https://github.com/salute-developers/GigaAM
- GigaAM ONNX: https://huggingface.co/istupakov/gigaam-v3-onnx/tree/322c3b29492673eb7d0b434bfa9dfb8653e34d02
- Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR
- Qwen native HF checkpoint: https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf/tree/7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c
- Qwen model/processor API: https://huggingface.co/docs/transformers/model_doc/qwen3_asr
- Qwen processor source v5.13.0: https://github.com/huggingface/transformers/blob/v5.13.0/src/transformers/models/qwen3_asr/processing_qwen3_asr.py
- Whisper Russian Stage AW: https://huggingface.co/coriollon/whisper-large-v3-turbo-russian/tree/5554b84e24c83794d6b25a10fc58cf08d7e79a02
- NVIDIA Parakeet: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Parakeet ONNX: https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx/tree/8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce
- Silero: https://github.com/snakers4/silero-vad
- Silero ONNX: https://huggingface.co/onnx-community/silero-vad/tree/e71cae966052b992a7eca6b17738916ce0eca4ec

## Runtime

- ONNX-ASR loader API v0.12.0: https://github.com/istupakov/onnx-asr/blob/v0.12.0/src/onnx_asr/onnx_asr.py
- ONNX-ASR project/requirements: https://github.com/istupakov/onnx-asr
- ONNX Runtime CUDA execution provider: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html
- ORT GPU 1.24.4 wheels: https://pypi.org/project/onnxruntime-gpu/1.24.4/#files
- Transformers 5.13.0: https://pypi.org/project/transformers/5.13.0/
- PyTorch CUDA distributions: https://download.pytorch.org/whl/cu128/torch/
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- CTranslate2 installation: https://opennmt.net/CTranslate2/installation.html
- NVML: https://docs.nvidia.com/deploy/nvml-api/
- psutil: https://psutil.readthedocs.io/

## Bootstrap и FFmpeg

- uv managed Python: https://docs.astral.sh/uv/concepts/python-versions/
- uv releases: https://github.com/astral-sh/uv/releases/tag/0.10.9
- uv Windows ZIP: https://releases.astral.sh/github/uv/releases/download/0.10.9/uv-x86_64-pc-windows-msvc.zip
- ZIP SHA-256: `f58dc40896000229db7c52b8bdd931394040ef2ad59abd1eda841f6d70b13d7a`
- FFmpeg: https://ffmpeg.org/documentation.html
- Gyan Windows builds: https://www.gyan.dev/ffmpeg/builds/
- FFmpeg 8.1.2 ZIP: https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip
- ZIP SHA-256: `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec`

Исполняемые bootstrap-артефакты проверяются по закреплённым SHA до использования. По модели сохраняются manifest/revision, размеры, локальный SHA каждого файла и факт проверки доступного upstream LFS SHA.

## Браузер, шрифты, интерфейс

- MDN File.name: https://developer.mozilla.org/en-US/docs/Web/API/File/name
- Windows WM_DROPFILES: https://learn.microsoft.com/en-us/windows/win32/shell/wm-dropfiles
- Windows DragQueryFileW: https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-dragqueryfilew
- Vue: https://github.com/vuejs/core/tree/v3.5.13
- TypeScript: https://www.typescriptlang.org/
- Reduced motion: https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion
- Unbounded: https://github.com/google/fonts/tree/main/ofl/unbounded
- Golos Text: https://github.com/google/fonts/tree/main/ofl/golostext
- Commissioner: https://github.com/google/fonts/tree/main/ofl/commissioner

Шрифты не включены в ZIP. Установщик использует опубликованную Google Fonts версию на момент первой загрузки, сохраняет её SHA-256 и проверяет glyph coverage. В отличие от моделей, font revision не зафиксирована commit SHA; это ограничение точной визуальной воспроизводимости. Commissioner имеет оси FLAR, VOLM, slnt, wght, а не wdth.
