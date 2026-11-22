# Chatbot Module — Hệ thống Chatbot và Web Application

Mô-đun ứng dụng chính của dự án **Hanoi Explorer Chatbot (Hanoi Explorer AI)**, tích hợp các bộ xử lý ngôn ngữ tự nhiên tiếng Việt, cơ sở dữ liệu vector ngữ nghĩa, thuật toán xếp hạng đa tiêu chí, kết nối LLM Google Gemini và giao diện tương tác người dùng Flask Web.

## Purpose and structure / Mục đích và cấu trúc

Mục đích: Tiếp nhận các yêu cầu tư vấn địa điểm bằng tiếng Việt tự nhiên của người dùng, phân tích ý định và trích xuất ràng buộc, truy xuất và xếp hạng các địa điểm phù hợp nhất từ cơ sở dữ liệu 1.691 địa điểm Hà Nội, đồng thời sinh câu trả lời tư vấn đàm thoại có căn cứ và trực quan trên giao diện Web.

Cấu trúc thư mục chi tiết:

```text
bot/
├── main.py                    # Điểm khởi chạy máy chủ Flask Web tại http://127.0.0.1:5000
├── CONTRACTS.md               # Đặc tả hợp đồng dữ liệu và giao diện giữa các module
├── requirements.txt           # Danh sách các thư viện phụ thuộc (Flask, chromadb, pytest...)
├── .env.example               # Mẫu cấu hình biến môi trường
├── data/
│   └── hanoi_places_cleaned.json   # Tập dữ liệu 1.691 địa điểm sạch chuẩn hóa 14 trường
├── src/
│   ├── chatbot/               # Các module lõi xử lý logic của chatbot
│   │   ├── config.py          # Quản lý cấu hình, tham số và biến môi trường
│   │   ├── schemas.py         # Định nghĩa các schema dữ liệu và cấu trúc truy vấn/phản hồi
│   │   ├── data_loader.py     # Tải và tiền kiểm tra dữ liệu địa điểm từ JSON
│   │   ├── embedding.py       # Tải và quản lý mô hình vector embedding (sentence-transformers)
│   │   ├── chroma_manager.py  # Quản lý kết nối và thao tác với ChromaDB
│   │   ├── query_processor.py # Phân tích ngữ tự nhiên tiếng Việt, trích xuất intent & entities
│   │   ├── retriever.py       # Truy xuất địa điểm theo vector ngữ nghĩa và bộ lọc cứng
│   │   ├── recommender.py     # Thuật toán xếp hạng đa tiêu chí và chuẩn hóa trọng số động
│   │   ├── memory.py          # Quản lý bộ nhớ phiên hội thoại nhiều lượt (ConversationMemory)
│   │   ├── prompts.py         # Mẫu System Prompt và Few-Shot kiểm soát định dạng trả về
│   │   ├── gemini_client.py   # Client kết nối Gemini REST API kèm cơ chế retry
│   │   └── chatbot.py         # Module điều phối tổng thể toàn bộ luồng xử lý truy vấn
│   └── web/                   # Ứng dụng Flask Web Interface
│       ├── app.py             # Khởi tạo Flask Application và đăng ký routes
│       ├── routes/            # Các endpoint API (/api/chat, /api/places, /api/sessions...)
│       ├── services/          # Tầng nghiệp vụ xử lý phiên và gọi chatbot
│       ├── templates/         # Giao diện HTML (index.html)
│       └── static/            # CSS, JavaScript và tài nguyên giao diện
├── scripts/                   # Kịch bản thực thi và đánh giá
│   ├── index_data.py          # Lập chỉ mục 1.691 địa điểm vào ChromaDB
│   ├── evaluate.py            # Chạy đánh giá độ chính xác truy xuất
│   └── run_baseline.py        # Chạy bộ chuẩn benchmark (120 ca baseline; 187 ca với --legacy)
├── evaluation/                # Dữ liệu và báo cáo benchmark
│   ├── BASELINE.md            # Tài liệu đặc tả phương pháp và tập dữ liệu đánh giá
│   ├── baseline_cases.json    # Tập 120 ca kiểm thử thực nghiệm (92 dev + 28 holdout)
│   ├── test_baseline.py       # Kiểm định tự động qua pytest
│   └── reports/               # Báo cáo kết quả chi tiết
└── tests/                     # Bộ 67 bài kiểm thử tự động (unit tests & integration tests)
```

## Requirements and setup / Yêu cầu và cài đặt

1. **Yêu cầu hệ thống:**
   - Python 3.10 trở lên.

2. **Cài đặt môi trường ảo và thư viện:**
   - Trên Windows (PowerShell):
     ```powershell
     python -m venv project/bot/.venv
     project/bot/.venv\Scripts\Activate.ps1
     pip install -r project/bot/requirements.txt
     ```
   - Trên Linux / macOS:
     ```bash
     python3 -m venv project/bot/.venv
     source project/bot/.venv/bin/activate
     pip install -r project/bot/requirements.txt
     ```

3. **Cấu hình biến môi trường:**
   - Sao chép tệp mẫu cấu hình:
     ```powershell
     Copy-Item project/bot/.env.example project/bot/.env
     ```
   - Các biến cấu hình chính trong `.env`:
     - `CHROMA_PATH`: Đường dẫn thư mục lưu trữ ChromaDB (mặc định: `chroma_db`).
     - `CHROMA_COLLECTION`: Tên collection (mặc định: `hanoi_cleaned_minilm_v1`).
     - `GEMINI_API_KEY`: Khóa API Google Gemini (tùy chọn; để trống hệ thống sẽ chạy bằng cơ chế deterministic fallback).
     - `GEMINI_MODEL`: `gemini-flash-lite-latest`.

4. **Tải mô hình nhúng và lập chỉ mục ChromaDB (chạy lần đầu):**
   ```bash
   python -m project.bot.scripts.index_data
   ```

## Inputs and outputs / Đầu vào và đầu ra

- **Đầu vào API (`POST /api/chat`):**
  - Payload JSON gửi từ client:
    - `message`: Chuỗi văn bản tiếng Việt tự nhiên (tối đa 500 ký tự).
    - `category`: Bộ lọc danh mục từ UI (tùy chọn: `Ẩm thực`, `Quán cà phê`,...).
    - `district`: Bộ lọc quận từ UI (tùy chọn: `Hoàn Kiếm`, `Cầu Giấy`,...).
    - `budget`: Bộ lọc ngân sách từ UI (tùy chọn).
    - `session_id`: Định danh phiên trao đổi phục vụ lưu ngữ cảnh đa lượt.
- **Đầu ra API (`POST /api/chat`):**
  - Payload JSON trả về cho client:
    - `answer` / `reply`: Lời tư vấn tiếng Việt tự nhiên, giải thích rõ lý do gợi ý phù hợp.
    - `places` / `recommendations`: Danh sách Top-5 địa điểm phù hợp nhất đã kiểm chứng ID (`validate_ids()`), đầy đủ thông tin chi tiết (tên, danh mục, địa chỉ, khoảng giá, giờ mở cửa, độ tương thích thời tiết).
    - `follow_up`: Câu gợi ý hỏi tiếp hoặc câu hỏi làm rõ nhu cầu khi thông tin chưa đầy đủ.
    - `status`: Trạng thái xử lý (`success`, `clarification_needed`...).
    - `itinerary`: `null` (chủ động tắt để đảm bảo độ chính xác).
- **Các API danh mục và phiên:**
  - `GET /api/places`: Danh mục đầy đủ 1.691 địa điểm phục vụ catalog.
  - `GET /api/categories`: Danh mục các nhóm trải nghiệm chuẩn hóa.
  - `GET /api/districts`: Danh sách 12 quận nội thành Hà Nội.
  - `POST /api/sessions`: Cấp mã phiên mới ngẫu nhiên.
  - `DELETE /api/sessions/<id>`: Xóa bộ nhớ của một phiên.
  - `GET /api/health`: Kiểm tra trạng thái sẵn sàng của dịch vụ.

## Reproduce the main result / Tái tạo kết quả chính

1. **Khởi chạy ứng dụng Web Chatbot:**
   ```bash
   python project/bot/main.py
   ```
   Mở trình duyệt web tại: `http://127.0.0.1:5000`.

2. **Chạy bộ kiểm thử tự động (67 bài unit tests & integration tests):**
   ```bash
   python -B -m unittest discover -s project/bot/tests -v
   ```
   - **Kết quả:** Toàn bộ **67/67 bài kiểm thử đều đạt (`OK`)** trong thời gian thực thi dưới 1 giây.

3. **Chạy kiểm định 70 ca xử lý NLP (`QU`, `CM`, `CR`):**
   ```bash
   python -m pytest project/bot/evaluation/test_baseline.py -k "QU or CM or CR" -v
   ```
   - **Kết quả:** Đạt **70/70 ca passed (100%)**.

4. **Chạy đánh giá bộ chuẩn thực nghiệm Baseline 120 ca (187 ca khi kèm `--legacy`):**
   ```bash
   python -m project.bot.scripts.run_baseline --split development --output project/bot/evaluation/reports-dev
   # Hoặc chạy đầy đủ 120 ca baseline + 67 ca unittest/tích hợp:
   python -m project.bot.scripts.run_baseline --legacy
   ```

## Known limitations / Giới hạn đã biết

- **Lưu trữ phiên trong bộ nhớ RAM:** `ConversationMemory` quản lý phiên theo thời gian sống (TTL = 3600s), dữ liệu bộ nhớ sẽ được làm mới khi máy chủ khởi động lại.
- **Tọa độ địa lý và lộ trình di chuyển:** Dữ liệu tọa độ GPS kế thừa từ tâm phố/quận nên chưa hỗ trợ tính khoảng cách di chuyển chính xác và chưa tối ưu hóa lộ trình đa điểm (`itinerary: null`).
- **Dịch vụ thời tiết thời gian thực:** Endpoint `/api/weather` trả về `unavailable` do chưa tích hợp dịch vụ thời tiết trực tiếp, hệ thống hiện dùng trường tĩnh `weather_fit` để lọc không gian trong nhà hoặc ngoài trời.
- **Đánh giá văn phong câu hỏi mở:** Các ca kiểm thử gọi trực tiếp tới Gemini (`GG-13..15`) và các câu hỏi mở cần thẩm định con người để đánh giá chất lượng phản hồi một cách toàn diện.
