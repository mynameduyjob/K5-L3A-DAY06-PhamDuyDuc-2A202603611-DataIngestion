# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang: *Adventures of Huckleberry Finn*, Chương I–XII, Project Gutenberg eBook #76 (Mark Twain; public domain tại Hoa Kỳ, giữ license/attribution trong `starter/data/huck_finn_pg76.txt`). Text không phân trang: 51 unit, 136.972 ký tự NFC; mỗi unit ≥1.500 ký tự, không nhân bản; trang vật lý N/A. Manifest: `starter/manifest.json`.
- Chuẩn hóa, lỗi và giới hạn: đọc UTF-8, NFC và chuẩn hóa whitespace; không cần OCR. Lần chạy benchmark hiện khóa bị OpenRouter HTTP 429 trước khi có embedding; không có vector/retrieval mới cho bộ này.
- Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí: OpenRouter `nvidia/nemotron-3.5-embed-1b:free`, 2048 chiều; document/query dùng cùng model. PostgreSQL 16.16 + pgvector 0.8.7, exact cosine `<=>`, không ANN; Docker image `pgvector/pgvector:0.8.7-pg16`. Chạy từ `starter/`: `docker compose up -d postgres`, `python -m src.run`. Chi phí API: 0 USD (free tier). Python 3.12.0; psycopg 3.3.8, pypdf 6.21.4, python-dotenv 1.2.4.
- Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn: `document_id`, `source`, `page` (surrogate theo unit), `unit_id`, offsets ký tự; `chapter` lấy từ heading nguồn, dùng để lọc và truy vết. Kiểu/giá trị chi tiết ở `starter/manifest.json` và metadata của trace.

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C): A fixed 500 ký tự, overlap 50; B chia theo đoạn, tối đa 1.000 ký tự; C dùng cùng chunk/vector với B và áp chapter filter khi câu hỏi cung cấp. A/B/C dùng cùng pgvector, model và cosine.
- ≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence: Benchmark đã khóa hiện tại có 23 câu (18 dev / 5 test), 9 filter (4 dev / 5 test); evidence được kiểm tra trên text đã chuẩn hóa. Bộ có số đo cũ là 20 câu (15/5), 4 filter (2/2), snapshot SHA-256 `cb57d1cfaed514f4eec07ef5c326aa91a6786c10fb78e481f34226504bcd35bb`. Snapshot cũ có rủi ro rò rỉ, không phải holdout độc lập.
- Tiêu chí chọn chiến lược đã chốt trước khi xem test: Chưa chốt trước; kết luận bên dưới là hồi cứu trên snapshot cũ, không áp dụng cho benchmark 23 câu.

## Kết quả
Kết quả retrieval dưới đây dùng snapshot cũ; thời gian là embedding tài liệu, C tái sử dụng vector B. Benchmark 23 câu mới chưa có kết quả do HTTP 429.

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---:|---:|---:|---:|---:|
| A | Dev | 4/15 | 5/15 | 325 | 27,77 giây | 0 USD |
| A | Test cũ | 4/5 | 4/5 | 325 | 27,77 giây | 0 USD |
| B | Dev | 2/15 | 7/15 | 202 | 16,61 giây | 0 USD |
| B | Test cũ | 2/5 | 4/5 | 202 | 16,61 giây | 0 USD |
| C | Dev | 2/15 | 7/15 | 202 | 0 giây thêm; dùng vector B | 0 USD |
| C | Test cũ | 2/5 | 4/5 | 202 | 0 giây thêm; dùng vector B | 0 USD |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---:|---:|---:|---|
| A | 1,0 (10) | 15/15 | 1/2 | 1/0/4; 1,6/2 |
| B | 1,5 (10) | 15/15 | 0/2 | 1/0/4; 1,6/2 |
| C | 1,5 (10) | 15/15 | 2/2 | 1/0/4; 1,6/2 |

Đường dẫn trace, nhãn thủ công và cách chọn mẫu: `starter/results/traces.json` (60 traces, 20 câu × 3 chiến lược); `starter/results/metadata_audit_exploratory.csv` (15 kết quả top-3 mỗi chiến lược); `starter/results/manual_audit_exploratory.csv` (grounding); `starter/results/coherence_audit_current.csv` (10 anchor chung, unit 2, 7, …, 47). Grounding/coherence là nhãn AI hỗ trợ, chưa được người học xác nhận độc lập. Lỗi benchmark mới: `starter/results/last_error.json`.

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn: B tăng Evidence Hit@3 dev từ 5/15 lên 7/15 nhưng Hit@1 giảm từ 4/15 xuống 2/15. B/C có cùng retrieval; C tuân thủ filter tốt hơn trên snapshot cũ. q08: B không lấy được evidence về 6.000 đô (gold `chapter-04-unit-02`). q19: cả ba bỏ sót tên cải trang Sarah Williams (gold `chapter-11-unit-01`).
- Chiến lược chọn, đánh đổi, điều kiện áp dụng: chọn C có điều kiện khi câu hỏi cung cấp chapter filter: Hit@3 ngang B, filter đúng 2/2 câu test cũ. A có Hit@1 cao hơn. Lựa chọn hồi cứu trên mẫu nhỏ.
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí: test cũ đã được xem và có rủi ro rò rỉ; benchmark 23 câu mới chưa chạy do quota. Nhãn grounding/coherence cần người học xác nhận. Thời gian tổng, token usage lịch sử chưa được ghi; không suy rộng ngoài corpus. Snapshot cũ có trace đầy đủ; chi phí free tier là 0 USD.
- Nếu làm lại hoặc mở rộng, cải tiến gì? Chạy benchmark 23 câu đã khóa sau quota reset; chấm nhãn thủ công độc lập, ghi tổng runtime/token usage và dùng corpus/query mới để giảm rò rỉ.
