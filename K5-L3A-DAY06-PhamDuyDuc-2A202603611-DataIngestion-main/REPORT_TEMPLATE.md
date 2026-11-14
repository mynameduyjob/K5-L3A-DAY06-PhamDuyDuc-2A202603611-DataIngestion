# Báo cáo cá nhân — Day 6: Data Ingestion Engineering

> **Trạng thái:** đã chuẩn bị corpus, manifest và pipeline; benchmark 23 câu đã khóa và xác thực. Lần chạy bộ 23 câu bị OpenRouter từ chối HTTP 429 ở request embedding tài liệu đầu tiên, nên không có vector hay retrieval mới. Để có số liệu so sánh, phần kết luận định lượng dưới đây dùng lần chạy có sẵn trên snapshot exploratory 20 câu (15 dev / 5 test), với đủ 60 trace top-3. Đây là phân tích hồi cứu: test cũ đã được xem và các chương test từng xuất hiện trong lần chạy exploratory, nên không xem là holdout độc lập. Bộ 23 câu vẫn được giữ nguyên, không thay nhãn hay giả lập kết quả.

## Dữ liệu và pipeline

- **Chủ đề:** phần mở đầu về hành trình của Huck Finn trong *Adventures of Huckleberry Finn*, Chương I–XII.
- **Nguồn:** Project Gutenberg eBook #76, Mark Twain, [catalog page](https://www.gutenberg.org/ebooks/76). File gốc `starter/data/huck_finn_pg76.txt` được giữ nguyên, gồm notice và toàn văn license Project Gutenberg. Catalog ghi tác phẩm public domain tại Hoa Kỳ; Mark Twain mất năm 1910. Điều 27(2)(b) của [Luật Sở hữu trí tuệ Việt Nam trên WIPO Lex](https://www.wipo.int/wipolex/en/legislation/details/12011) quy định thời hạn cho tác phẩm thuộc nhóm này là đời tác giả cộng 50 năm, nên thời hạn bảo hộ kinh tế đã hết trước ngày truy cập ghi dưới đây. Ghi công Mark Twain và Project Gutenberg; chỉ sử dụng trong bài lab giáo dục phi thương mại.
- **Thời điểm truy cập / snapshot:** 2026-11-14; bản plain text eBook #76, header của file ghi cập nhật gần nhất 2026-05-17.
- **Phạm vi và cách đếm:** nguồn text không có phân trang. Lấy Chương I–XII, chuẩn hóa NFC và whitespace, rồi chia theo ranh giới đoạn thành 51 unit có thứ tự, mỗi unit gần 3.000 ký tự; phần cuối dưới 1.500 ký tự được gộp vào unit trước cùng chương. Manifest ghi `unit_id`, chương, page surrogate, offset ký tự chuẩn hóa đầu/cuối và số ký tự. Có 51 unit, tổng 136.972 ký tự; tất cả unit đạt ngưỡng 1.500 ký tự, không nhân bản. Không có trang vật lý; `physical_pages` là N/A.
- **Manifest và dữ liệu:** `starter/manifest.json`; quy tắc quyền và nguồn nằm tại `starter/data/SOURCE_ATTRIBUTION.md`. Loader xác minh lại số ký tự và ranh giới từng unit khi nạp.
- **Đọc và chuẩn hóa:** `starter/src/ingestion.py` đọc UTF-8, chuẩn hóa Unicode NFC và whitespace, gắn `unit_id`, chapter, source, trạng thái trích xuất và vị trí. Không cần OCR. Văn bản có phương ngữ lịch sử và ngôn ngữ phân biệt chủng tộc; đây là nội dung gốc được giữ trong ngữ cảnh lịch sử, không phải quan điểm của người làm bài.
- **Embedding:** OpenRouter, model thật `nvidia/nemotron-3.5-embed-1b:free`, 2048 chiều; model/chiều đã trả vector thành công ở lần chạy exploratory trước. Cả chunk tài liệu và query đi qua cùng endpoint/model và cùng cách chuẩn hóa input. Cần `OPENROUTER_API_KEY` và `EMBEDDING_MODEL` trong `starter/.env`; key không ghi vào repo/báo cáo. Đây là model free-tier, chi phí dịch vụ chọn là **0 USD**. Lần chạy hiện tại bị từ chối do daily quota trước khi trả vector. Adapter mới ghi request/token/cost usage nếu provider trả về; token usage của lần chạy lịch sử không được lưu nên hiện không có số token đáng tin.
- **Môi trường phần mềm:** Python 3.12.0; `psycopg[binary]` 3.3.8, `pypdf` 6.21.4, `python-dotenv` 1.2.4; PostgreSQL 16.16 và pgvector 0.8.7. Ràng buộc dependencies của repo nằm trong `starter/requirements.txt`. Retrieval exact cosine và chunking không lấy mẫu ngẫu nhiên, nên không cần seed ngẫu nhiên.
- **Vector store/search:** Docker image `pgvector/pgvector:0.8.7-pg16`; setup xác nhận PostgreSQL 16.16, pgvector 0.8.7, database `day6_lab`, bảng bền vững `public.document_chunks`. Khởi tạo từ `starter/` bằng `docker compose up -d postgres`; kết nối qua `DATABASE_URL` trong `.env` (không ghi credential vào report). Ba cấu hình dùng cùng store, `vector(2048)` và exact cosine distance (`<=>`), không có ANN index. Backend lỗi thì pipeline dừng và ghi lỗi, không fallback mock.
- **Đo ingest/tài nguyên:** báo cáo run ghi chunk count, histogram và min/median/max độ dài, tổng ký tự chunk, provider prompt/total tokens khi có usage, thời gian chunking, embedding, transaction upsert, retrieval và tổng runtime. Model `:free` ghi chi phí 0 USD. Lần chạy mới ghi được chunking A/B khoảng 0,002 giây mỗi cấu hình; embedding A dừng sau khoảng 1,47 giây ở HTTP 429, không nhận vector/token usage. Ký tự nguồn (không nhân overlap) là 136.972; token count của lần chạy lịch sử không có.
- **Nạp lại và thay đổi nguồn:** mỗi strategy được xóa rồi nạp lại trong một transaction; khóa chính `(strategy, chunk_id)` và kiểm tra row count sau upsert ngăn nhân đôi. Khi nội dung/manifest đổi, pipeline đọc lại nguồn, tạo chunk ID mới theo text/vị trí và thay thế index strategy ở lần chạy tiếp. Nếu transaction lỗi, transaction đó rollback. Runner đã được cập nhật để ghi checkpoint vào `run_progress.json` và ghi hash benchmark, model, stage, strategy cùng lỗi vào `last_error.json`; lần 429 hiện tại đã được bổ sung các thông tin truy vết này.
- **Kiểm tra nạp lại:** `starter/results/store_snapshot_audit.json` ghi lần thay thế A/B/C bằng chính các vector thật đã lưu từ lần chạy model thành công trước. Mỗi strategy giữ đúng 325/202/202 row, tất cả ID/text/metadata/vector khớp và không có ID trùng. Thời gian upsert với vector đã cache: A 1,11 giây; B 0,71; C 0,69. Đây là kiểm tra idempotency/store, không phải thời gian embedding hay tổng ingest mới.
- **Metadata:** `document_id` (`text`, source ID), `source` (`text`, title từ manifest), `page` (`integer`, page surrogate là thứ tự unit), `unit_id` (`text`, manifest), `chapter` (`text`, heading chương của sách), `char_start`/`char_end`/`char_count` (`integer`, vị trí/số ký tự sau chuẩn hóa), `extraction_status`/`location_type` (`text`, loader). `chapter` là filter có các giá trị I–XII thật trong nguồn; input câu hỏi nêu chapter trước retrieval. Không tự gán năm hoặc ngày hiệu lực.
- **Lệnh chạy:** từ `starter/`, `python -m src.run`. Manifest được tạo bằng `python scripts/build_text_manifest.py`; benchmark mới được tạo bằng `python scripts/build_benchmark.py` rồi khóa bằng `python scripts/freeze_benchmark.py` trước lần chạy đầu. Benchmark hiện tại đã khóa, nên không chạy lại builder/freeze; kiểm tra PostgreSQL bằng `python scripts/check_setup.py`.
- **AI và kiểm tra:** AI hỗ trợ code, viết câu hỏi/evidence draft và phân tích trace. Validator kiểm tra 51 unit, 23 câu, evidence được chấp nhận, split, filter và ranh giới chương; người nộp cần đọc lại câu hỏi, đáp án và nhãn trước khi nộp. Các nhãn coherence/grounding trong artifact hiện là bản đánh giá AI hỗ trợ, chưa được người học xác nhận độc lập.

## Cấu hình và benchmark

| Strategy | Chunking | Tham số | Filter |
|---|---|---|---|
| A | Fixed-size | 500 ký tự, overlap 50 | Không |
| B | Theo đoạn | Tối đa 1.000 ký tự; đoạn dài được chia theo ký tự | Không |
| C | Giống B | Cùng chunk và vectors như B | Filter chapter lấy từ input câu hỏi |

B–C chỉ khác ở filter retrieval. Câu hỏi không có filter vẫn chạy không filter ở C.

- `starter/benchmark.json` hiện được khóa thành 23 câu: 18 dev / 5 test; 9 câu có filter, gồm 4 dev và 5 test. Loại câu: 9 trực tiếp, 8 diễn đạt lại, 5 điều kiện và 1 ngoại lệ. Dev nằm ở chương I–VIII, test ở chương IX–XII, không trùng chương giữa hai split. Evidence được đối chiếu với unit/chapter gold; filter tồn tại trong metadata và được nêu trong câu hỏi trước truy xuất. A/B/C cùng đọc một list benchmark, nên cùng tập câu và nhãn.
- Mỗi câu có `accepted_evidence`; hiện mỗi câu có một đoạn được xác minh. Schema và evaluator cho phép liệt kê nhiều nguồn/trang/unit hợp lệ và chấp nhận bất kỳ đoạn nào trong danh sách. `benchmark.lock.json` ghi SHA-256 `2a5e8cbc17c9bd6be4677c726f701c459eed36e89cb36d74f0d9c3f97847f42c`, số lượng/split, loại câu, nhóm chương và ID test. Runner từ chối chạy nếu file benchmark khác hash đã khóa.
- Bộ câu hỏi đã khóa chưa chạy retrieval. Tuy nhiên, các câu test mới được chuẩn bị sau khi đã xem kết quả của benchmark exploratory trước đó, trong đó có các chương VIII–XII. Việc tách chương giảm rò rỉ giữa dev/test của bộ hiện tại nhưng **không xóa được rủi ro rò rỉ từ lần thử trước**; không gọi đây là holdout độc lập và không dùng số test cũ cho bộ này.
- Không sửa benchmark sau lần chạy đầu. Nếu phát hiện lỗi sau khi chạy, lưu nguyên bản và kết quả, tạo phiên bản benchmark mới với ID/hash mới, rồi ghi rõ kết quả phiên bản mới là exploratory.
- Tiêu chí lựa chọn strategy chưa chốt cho lần chạy tiếp. Chọn cấu hình trên dev, ghi tiêu chí trước khi truy cập kết quả test; chạy đúng file/hash đã khóa khi quota cho phép. Do đã xem kết quả test trước, không thể tuyên bố test này hoàn toàn độc lập.

## Kết quả retrieval

### Dev — q01–q15 dùng chung với lần chạy exploratory trước

Metrics dưới đây chỉ tính q01–q15, là phần dev giữ nguyên. Benchmark hiện tại có thêm q16–q18 trong dev, nên các số này **không phải kết quả trên toàn bộ 18 câu dev hiện tại**.

| Strategy | Hit@1 trên q01–q15 | Evidence Hit@3 trên q01–q15 | Chunk count | Thời gian embedding tài liệu | Chi phí |
|---|---:|---:|---:|---:|---|
| A | 4/15 | 5/15 | 325 | 27,77 giây | 0 USD (`:free`) |
| B | 2/15 | 7/15 | 202 | 16,61 giây | 0 USD (`:free`) |
| C | 2/15 | 7/15 | 202 | 0 giây thêm; dùng vectors B | 0 USD (`:free`) |

Query embedding dùng chung cả ba strategy mất 2,00 giây trong lần chạy thành công, chi phí 0 USD (`:free`). A có 150.569 ký tự chunk sau overlap; B/C có 136.728 ký tự. Thời gian trên là thời gian embedding, không phải tổng runtime; thời gian chunking, upsert và token usage của lần chạy lịch sử chưa được ghi.

### Test của lần chạy có số liệu — snapshot exploratory cũ

Trace và summary cho lần chạy này được lưu cùng snapshot câu hỏi đã dùng.

| Strategy | Hit@1 | Evidence Hit@3 | Filter tuân thủ trên câu có filter |
|---|---:|---:|---:|
| A | 4/5 | 4/5 | 1/2 |
| B | 2/5 | 4/5 | 0/2 |
| C | 2/5 | 4/5 | 2/2 |

Đây là năm câu test của snapshot 20 câu, đã được xem trước khi thay benchmark. Snapshot có 15 dev / 5 test và 4 câu filter (2 dev / 2 test); SHA-256 `cb57d1cfaed514f4eec07ef5c326aa91a6786c10fb78e481f34226504bcd35bb`. Dùng các số này chỉ để chốt mô tả trong phạm vi lần chạy cũ; không gán chúng cho bộ 23 câu hiện tại.

### Test đã khóa hiện tại — chưa chạy

Chưa có kết quả retrieval cho bộ 23 câu này. Lần chạy mới lúc `2026-11-14T04:19:31Z` xác thực lock, dựng chunk A/B/C, rồi OpenRouter trả HTTP 429 `free-models-per-day` ở batch embedding A đầu tiên. Không có vector, query embedding, top-3 hay metrics mới. `last_error.json` ghi lỗi/hash/model/stage; `run_progress.json` ghi split, chunk counts, ký tự và thời gian đến lúc lỗi. `summary.json` và `traces.json` vẫn là exploratory cũ, trỏ tới snapshot `results/benchmark_used_exploratory.json`. API báo quota đặt lại lúc `2026-11-15T00:00:00Z`.

## Audit năm khía cạnh

| Khía cạnh | Bằng chứng hiện có | Nhận xét và giới hạn |
|---|---|---|
| Retrieval | `summary.json` và 60 trace của snapshot exploratory 20 câu | Dev: A Hit@1 4/15, Hit@3 5/15; B/C 2/15, 7/15. Test cũ: A 4/5, 4/5; B/C 2/5, 4/5. Các tỷ lệ test này là hồi cứu, không độc lập. Bộ 23 câu khóa mới chưa chạy. |
| Coherence | `starter/results/coherence_audit_current.csv`: 10 vị trí cố định (unit 2, 7, …, 47), midpoint và chunk đầu tiên bao phủ vị trí; cùng vị trí cho A/B/C | Bản đọc AI hỗ trợ: A mức 0/1/2 = 0/10/0, trung bình 1,0/2; B/C = 0/5/5, trung bình 1,5/2. B và C giống chunk nên cùng điểm. Lý do từng mẫu ghi trong CSV; người học cần xác nhận. |
| Metadata usefulness | Audit top-3 exploratory cũ: 45/45 hàng khớp; `store_snapshot_audit.json` kiểm tra 729/729 chunk A/B/C khớp manifest, text và metadata trước/sau nạp lại | `chapter` có giá trị I–XII lấy từ heading và được dùng làm filter; `unit_id`/offset truy nguyên unit. Kiểm tra top-3 của bộ mới chưa có vì quota chặn trước embedding. |
| Grounding | `starter/results/manual_audit_exploratory.csv`: 5 câu test × 3 strategy | Nhãn AI hỗ trợ cho mỗi strategy: 4 câu mức 2, 0 câu mức 1, 1 câu mức 0; trung bình 1,6/2. Đây là chấm nháp, cần người học xác nhận và không áp dụng cho bộ 23 câu mới. |
| Data strategy impact | So sánh A–B và B–C trên cùng corpus/model/query | Trên lần chạy cũ, B/C có Hit@3 bằng nhau; C tuân thủ filter 2/2 câu test có filter so với A 1/2 và B 0/2. Model free có chi phí dịch vụ 0 USD; tổng runtime/token usage cũ chưa có. Kết luận chỉ trong corpus và truy vấn đã chạy. |

## Lỗi quan sát được và kết luận tạm thời

- **q08, dev:** hỏi Huck muốn Judge Thatcher làm gì với 6.000 đô; gold ở `chapter-04-unit-02`, nhưng top-3 của B nằm ở chương I, V và VI và không chứa evidence. Câu này cho thấy truy vấn ngắn có số tiền dễ lấy nhầm ngữ cảnh khác.
- **q19 trong test exploratory cũ:** hỏi tên Huck dùng khi cải trang; gold `Sarah Williams` nằm ở `chapter-11-unit-01`, nhưng top-3 cả ba strategy trả các unit ở chương III, VI, VIII/IX. Câu này đã được thay trong benchmark cuối và không đại diện cho kết quả test hiện tại.
- **Chốt có điều kiện từ số đo hiện có:** chọn C làm cấu hình đề xuất cho corpus này khi chapter filter có sẵn trong câu hỏi: trên snapshot cũ C giữ Hit@3 ngang B (dev 7/15, test 4/5), đồng thời lọc đúng cả 2/2 truy vấn test có filter; A có Hit@1 cao hơn trên tập cũ (dev 4/15, test 4/5) nhưng chỉ lọc đúng 1/2 truy vấn có filter. Đây là quyết định mô tả hồi cứu, không phải lựa chọn đã đăng ký trước khi xem test. Nếu không có filter, C và B có cùng cách chia chunk, nên số liệu không cho thấy C hơn B về retrieval.
- **Giới hạn:** corpus là một tác phẩm văn học, chỉ 12 chương; benchmark do một người soạn từ chính corpus; snapshot test dùng để kết luận là exploratory, đã được xem và có rủi ro rò rỉ; bộ 23 câu khóa mới bị quota chặn nên chưa có kết quả. Grounding/coherence là nhãn AI hỗ trợ, chưa được người học xác nhận. Chi phí model free là 0 USD; token usage và tổng runtime của lần chạy lịch sử chưa được ghi. Không suy rộng kết quả ra corpus khác.

## Artifacts và tái lập

- Corpus/license notes: `starter/data/huck_finn_pg76.txt`, `starter/data/SOURCE_ATTRIBUTION.md`.
- Manifest: `starter/manifest.json`; builder: `starter/scripts/build_text_manifest.py`.
- Benchmark đã khóa: `starter/benchmark.json`; builder: `starter/scripts/build_benchmark.py`; lock/hash: `starter/benchmark.lock.json`.
- Khóa benchmark đã tạo tại `starter/benchmark.lock.json`; công cụ tạo lock cho phiên bản mới là `starter/scripts/freeze_benchmark.py`. Không tạo lại lock cho bộ hiện tại. Từ `starter/`, `python -m src.run` kiểm tra hash trước khi gọi embedding API.
- Trace/summary exploratory và snapshot inputs: `starter/results/traces.json` (60 hàng = 20 câu × A/B/C, đủ 3 hit có text/score/metadata mỗi hàng), `starter/results/summary.json`, `starter/results/benchmark_used_exploratory.json` (20 câu, SHA-256 `cb57d1cfaed514f4eec07ef5c326aa91a6786c10fb78e481f34226504bcd35bb`).
- Metadata audit và nhãn AI hỗ trợ exploratory: `starter/results/metadata_audit_exploratory.csv`, `starter/results/manual_audit_exploratory.csv`. Phiếu grounding cho benchmark hiện tại: `starter/results/manual_audit_current.csv` (15 dòng, đang chờ retrieval top-3 và người chấm).
- Phiếu manual audit cho benchmark mới: `starter/results/manual_audit_current.csv` (15 dòng test × A/B/C; top-3 còn trống vì quota chặn trước retrieval). Lỗi lần chạy: `starter/results/last_error.json`; checkpoint từ các lần chạy sau: `starter/results/run_progress.json`. Chạy lại `python -m src.run` từ `starter/` sau khi quota được cấp lại; sau đó điền grounding/metadata labels thủ công và cập nhật các bảng.
- Audit vector store/nạp lại: `starter/scripts/audit_store_snapshot.py --reingest`; kết quả hiện tại: `starter/results/store_snapshot_audit.json`.
- Phiếu chunk coherence: `starter/results/coherence_audit_current.csv`; cách lấy mẫu và rubric ghi trong `starter/scripts/prepare_coherence_audit.py` / `score_coherence_audit_ai_draft.py`.
