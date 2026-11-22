# ==============================================================================
# Stage 1: Builder - Lập chỉ mục ChromaDB & tải bản ONNX INT8 cho MiniLM-L12-v2
# ==============================================================================
FROM python:3.11-slim AS builder

WORKDIR /app
COPY project/bot/requirements.txt /app/project/bot/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r /app/project/bot/requirements.txt huggingface_hub

COPY . /app
ENV PYTHONPATH=/app \
    SENTENCE_TRANSFORMERS_HOME=/app/project/bot/model_cache \
    HF_HOME=/app/project/bot/model_cache

# 1. Lập chỉ mục sẵn 1.691 địa điểm vào /app/project/bot/chroma_db
RUN python -m project.bot.scripts.index_data --force

# 2. Tải bản ONNX lượng tử hóa INT8 (113 MB) + SentencePiece (4.8 MB) và xóa cache PyTorch nặng
RUN python -c "\
from huggingface_hub import hf_hub_download; \
import shutil; \
out_dir = '/app/project/bot/onnx_model'; \
hf_hub_download('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'onnx/model_quint8_avx2.onnx', local_dir=out_dir); \
hf_hub_download('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'sentencepiece.bpe.model', local_dir=out_dir); \
shutil.move(f'{out_dir}/onnx/model_quint8_avx2.onnx', f'{out_dir}/model_quint8_avx2.onnx'); \
shutil.rmtree(f'{out_dir}/onnx', ignore_errors=True); \
shutil.rmtree('/app/project/bot/model_cache', ignore_errors=True)"

# ==============================================================================
# Stage 2: Runtime siêu nhẹ (< 260 MB RAM, vừa khít gói Free 512 MB của Render)
# ==============================================================================
FROM python:3.11-slim

RUN useradd -m -u 1000 user
WORKDIR /app

# Không cài torch/transformers/sentence-transformers ở runtime để tránh tràn 512MB RAM
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      "Flask>=3.1,<4" \
      "chromadb>=1.0,<2" \
      "python-dotenv>=1,<2" \
      gunicorn \
      onnxruntime \
      sentencepiece \
      numpy

COPY --from=builder --chown=user:user /app /app

USER user
ENV HOME=/home/user \
    PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=10000 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MALLOC_TRIM_THRESHOLD_=65536 \
    ANONYMIZED_TELEMETRY=False \
    GEMINI_MODEL=gemini-3.5-flash-lite \
    GEMINI_TIMEOUT_SECONDS=8 \
    GEMINI_MAX_RETRIES=1

EXPOSE 10000

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 2 --timeout 120 \"project.bot.src.web.app:create_app()\""]
