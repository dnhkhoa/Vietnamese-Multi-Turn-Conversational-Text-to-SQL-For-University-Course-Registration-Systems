# Model-only multi-turn benchmark sau fix

Ngày chạy: 2026-06-21

## Cấu hình

- Database: `ctdt_sis_v2_fixed.db`
- Model adapter: `models/qwen3b-lora-state-tracking`
- Parser mode: `hybrid`
- Model-only parser: bật
- Repair/normalizer: bật để chuẩn hóa JSON, entity và state trước khi chạy SQL
- Rule fallback trả lời thay model: không dùng trong benchmark này

## Kết quả tổng quan

- Tổng số flow: 5
- Tổng số turn: 25
- Số turn chạy được end-to-end: 25/25
- Parser source: `qwen` ở toàn bộ 25/25 turn
- Lỗi cũ đã hết trong bộ benchmark này:
  - Không còn lỗi rơi về danh sách 50/80 lớp không liên quan.
  - Không còn mất môn khi hỏi tiếp kiểu "còn buổi chiều thì sao".
  - Không còn mất metric khi đổi từ Machine Learning sang Cơ sở dữ liệu.
  - Không còn lỗi AI/CSDL/ML bị hiểu cứng theo một vài môn quen thuộc.

## Flow 1: lọc lớp CSDL nhiều lượt

| Turn | Câu hỏi | Kết quả chính |
| --- | --- | --- |
| 1 | Cho tôi xem các lớp của môn CSDL | 3 lớp Database System |
| 2 | Chỉ lấy lớp buổi sáng | 3 lớp buổi sáng |
| 3 | Lớp nào còn slot | 2 lớp còn chỗ |
| 4 | Đổi sang môn AI | 2 lớp Artificial Intelligence còn chỗ |
| 5 | Sắp xếp theo thứ trong tuần | 2 lớp AI, giữ đúng filter còn chỗ |
| 6 | Bỏ điều kiện buổi sáng | 2 lớp AI còn chỗ |

## Flow 2: hỏi thông tin môn và tiên quyết

| Turn | Câu hỏi | Kết quả chính |
| --- | --- | --- |
| 1 | Môn AI có bao nhiêu tín chỉ? | 3 tín chỉ |
| 2 | Môn này cần học trước môn gì? | 3 môn tiên quyết |
| 3 | Đổi sang môn NLP | Đổi state sang Natural Language Processing |
| 4 | Điều kiện tiên quyết của môn đó là gì? | 2 môn tiên quyết |

## Flow 3: CTĐT theo ngành, học kỳ, loại môn

| Turn | Câu hỏi | Kết quả chính |
| --- | --- | --- |
| 1 | Ngành CNTT có những môn bắt buộc nào? | 85 môn bắt buộc |
| 2 | Chỉ xem các môn ở học kỳ 5 | 7 môn |
| 3 | Đổi sang môn tự chọn | 2 môn tự chọn học kỳ 5 |
| 4 | Lấy 5 môn đầu tiên | Vẫn 2 môn vì chỉ có 2 kết quả |
| 5 | Bỏ điều kiện học kỳ | 5 môn tự chọn đầu tiên |

## Flow 4: đếm lớp và số sinh viên đăng ký

| Turn | Câu hỏi | Kết quả chính |
| --- | --- | --- |
| 1 | Với môn AI, CSDL, ML mỗi môn có bao nhiêu lớp? | AI: 3, CSDL: 3, ML: 2 |
| 2 | Chỉ đếm những lớp còn chỗ | AI: 2, CSDL: 2, ML: 2 |
| 3 | Có bao nhiêu sinh viên đăng ký môn Machine learning? | 8 sinh viên |
| 4 | Đổi sang môn Cơ sở dữ liệu | 69 sinh viên |

## Flow 5: quay lại chủ đề ban đầu

| Turn | Câu hỏi | Kết quả chính |
| --- | --- | --- |
| 1 | Cho tôi xem các lớp môn CSDL | 2 lớp CSDL mở |
| 2 | Đổi sang môn AI | 2 lớp AI mở |
| 3 | Quay lại môn ban đầu | 2 lớp CSDL mở |
| 4 | Môn đó có lớp nào vào buổi chiều? | 2 lớp CSDL buổi chiều |
| 5 | Chỉ lấy lớp còn chỗ | 2 lớp CSDL buổi chiều còn chỗ |
| 6 | Môn này có môn tiên quyết không? | Không có môn tiên quyết |

## Nhận xét

Benchmark này kiểm tra mục tiêu demo: model phải parse được intent/state, app giữ context nhiều lượt, SQL chạy ra dữ liệu đúng với DB mới. Kết quả này chưa thay thế evaluation chính thức trên toàn bộ dataset, nhưng đủ làm bằng chứng là end-to-end flow đã ổn hơn trước khi demo.

Raw output: `viedu-unsloth-local/outputs/freeform_eval/model_only_multiturn_after_fix.json`
