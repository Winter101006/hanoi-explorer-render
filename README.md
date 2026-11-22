---
title: Hanoi Explorer AI
emoji: 🍜
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Hanoi Explorer AI — Cloud Docker Deployment (ONNX INT8 + Modular RAG)

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Render%20Cloud-0284c7?style=for-the-badge&logo=render)](https://hanoi-explorer-ai.onrender.com/)
[![Main Repository](https://img.shields.io/badge/Full%20Source%20%26%20Eval-hanoi--explorer--ai-111827?style=for-the-badge&logo=github)](https://github.com/Winter101006/hanoi-explorer-ai)
[![Author](https://img.shields.io/badge/Author-Ph%E1%BA%A1m%20Ng%E1%BB%8Dc%20Hu%C3%A2n%20(@Winter101006)-2563eb?style=for-the-badge)](https://github.com/Winter101006)

Kho triển khai tối ưu cho môi trường đám mây (**Render Free Tier 512 MB RAM / Hugging Face Docker Spaces**) của hệ thống **Hanoi Explorer AI** — Chatbot tư vấn 1.691 địa điểm ăn uống, cà phê, di tích, không gian tâm linh, giải trí và ngoài trời tại 12 quận nội thành Hà Nội, phát triển hoàn chỉnh bởi **Phạm Ngọc Huân (`@Winter101006`)**.

> **Live Web App:** https://hanoi-explorer-ai.onrender.com/  
> **Kho mã nguồn đầy đủ (Crawler, Preprocessing, Tests & Benchmark 187 ca):** https://github.com/Winter101006/hanoi-explorer-ai

---

## Tối ưu hóa kiến trúc triển khai (Production Cloud Optimization)

Để vận hành mô hình tìm kiếm ngữ nghĩa tiếng Việt trên giới hạn bộ nhớ **512 MB RAM** mà vẫn giữ nguyên độ chính xác truy xuất, kho triển khai này áp dụng quy trình đóng gói **Multi-stage Docker Build**:

1. **Builder Stage:**
   - Nạp bộ dữ liệu sạch 1.691 địa điểm (`hanoi_places_cleaned.json`) và lập chỉ mục sẵn vào **ChromaDB** (`hnsw:space = cosine`, vector 384 chiều).
   - Tải trọng số **ONNX lượng tử hóa INT8 (`model_quint8_avx2.onnx`, ~113 MB)** và tokenizer **SentencePiece (~4.8 MB)** của `paraphrase-multilingual-MiniLM-L12-v2`, sau đó xóa toàn bộ cache PyTorch nặng.
2. **Slim Runtime Stage (`< 260 MB RSS RAM`):**
   - Loại bỏ hoàn toàn `torch`, `transformers` và `sentence-transformers` khỏi image chạy thực tế.
   - Sử dụng trực tiếp `onnxruntime` + `sentencepiece` + `numpy` (`_OnnxMiniLMEmbedder` trong `embedding.py`) kết hợp `gunicorn` (`1 worker, 2 threads`) và biến môi trường `PORT` tự động tương thích Render.
3. **Modular RAG & Anti-Hallucination Guardrails:**
   - Bộ hiểu truy vấn tiếng Việt tất định (`QueryProcessor` + `menu.py`), lọc ràng buộc cứng tại biên (`_eligible`), xếp hạng đa tiêu chí thích ứng (`Recommender`), hậu kiểm JSON Schema cho Google Gemini API và cơ chế fallback tất định khi thiếu API key.

## Chạy bằng Docker

```bash
docker build -t hanoi-explorer-render .
docker run -p 10000:10000 -e GEMINI_API_KEY=your_api_key hanoi-explorer-render
```

## Tác giả

- **Phạm Ngọc Huân** (`@Winter101006`) — https://github.com/Winter101006
