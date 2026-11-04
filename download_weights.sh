#!/usr/bin/env bash
# Descarga manualmente VisionPsy-Nano y compila llama.cpp; el scaffold nunca ejecuta este archivo.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
for command in python git cmake; do
  command -v "$command" >/dev/null || { echo "Falta la herramienta: $command" >&2; exit 1; }
done
python -m pip install 'huggingface_hub>=0.27,<2'
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='qvac/VisionPsy-Nano-460M', local_dir='models/visionpsy-nano')"
if [[ ! -d llama.cpp ]]; then
  git clone https://github.com/ggml-org/llama.cpp.git llama.cpp
fi
cmake -S llama.cpp -B llama.cpp/build
cmake --build llama.cpp/build --config Release --parallel
echo 'Descarga y compilación terminadas. Selecciona el GGUF y su proyector multimodal compatible.'
echo 'Si el repositorio no contiene GGUF, conviértelo siguiendo la documentación del modelo.'
echo 'Conecta el adaptador real y ajusta models.vision.gguf_path antes de elegir llamacpp.'
