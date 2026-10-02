# Third-party notices

The SLOI application code is distributed under MIT (see LICENSE). Upstream packages, downloaded model weights, fonts and tools retain their own licenses. This source archive does not redistribute model weights, Python/CUDA executables, FFmpeg executables, or font files.

## Vue 3.5.13 (bundled)

`frontend/public/vendor/vue.global.js` and the corresponding production copy contain Vue.js. License: MIT.

Copyright (c) 2018-present, Yuxi (Evan) You and Vue contributors.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Downloaded model artifacts

The installer retains available upstream license/readme files. Repository cards/licenses at the selected revisions are authoritative; a conversion does not erase upstream model conditions.

| Artifact | Attribution / repository | Declared license |
|---|---|---|
| GigaAM v3 ONNX | ai-sage / salute-developers; ONNX export by istupakov | MIT |
| Qwen3-ASR 0.6B HF | Qwen | Apache-2.0 |
| Whisper Russian Stage AW | coriollon, based on Whisper | Apache-2.0 as declared by fine-tune repository; upstream Whisper MIT |
| Parakeet TDT v3 ONNX | NVIDIA; ONNX export by istupakov | CC-BY-4.0 |
| Silero ONNX | Silero/snakers4; onnx-community conversion | MIT |

Model source URLs and exact revisions are in `config/models.manifest.json` and `docs/SOURCES.md`. SLOI applies runtime preprocessing/segmentation; it does not claim authorship of the models or endorsement by their authors. Preserve model attribution when redistributing the downloaded weights. CC-BY-4.0: https://creativecommons.org/licenses/by/4.0/

## Downloaded dependencies and assets

- uv: Astral, MIT / Apache-2.0; see upstream project notices.
- CPython and python-build-standalone: PSF / upstream bundled component licenses.
- PyTorch: BSD-style license; NVIDIA CUDA/cuDNN components have separate NVIDIA terms.
- ONNX Runtime, ONNX-ASR, CTranslate2, faster-whisper: upstream MIT licenses.
- Transformers: Apache-2.0.
- FastAPI, Vue, TypeScript, psutil and other dependencies retain their upstream terms. Installed wheel metadata includes their notices.
- FFmpeg Windows build by Gyan: GPLv3 build; downloaded directly by installer, not embedded in this archive. Build/source links: https://www.gyan.dev/ffmpeg/builds/ and https://ffmpeg.org/ . Runtime tool notices are retained under `runtime/ffmpeg/notices`.
- Unbounded, Golos Text, Commissioner: SIL Open Font License 1.1, downloaded from Google Fonts by installer. Corresponding OFL files are saved alongside local installed fonts. No font binaries are redistributed in this source archive.

User-provided design references are inspiration only; screenshots, portraits, brand logos and third-party UI artwork from those references are not bundled or copied into SLOI.
