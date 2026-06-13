# Production Data Improvements

## Đã xử lý trong package này

### 1. COURSE_RECOMMENDATION thành intent chính thức

- Thêm `COURSE_RECOMMENDATION` vào `ALLOWED_INTENTS`.
- Thêm intent aliases: `RECOMMEND_COURSES`, `SUGGEST_COURSES`, `SUGGEST_REGISTRATION`, `COURSE_ADVICE`, `ACADEMIC_ADVICE`.
- Tích hợp backend execution trong `VietnameseNL2SQLEngine`.

### 2. Recommendation có logic học vụ rõ hơn

Module `src/recommendation_engine.py` gợi ý môn dựa trên:

- Sinh viên còn đang học hay không.
- CTĐT của sinh viên.
- Môn đã đạt.
- Môn đã rớt nên ưu tiên học lại.
- Lớp mở ở học kỳ hiện tại.
- Lớp còn chỗ.
- Thiếu tiên quyết.
- Trùng lịch.
- Đã đăng ký môn/lớp chưa.
- Giới hạn tín chỉ `MAX_CREDITS_PER_SEMESTER`.
- Ưu tiên môn bắt buộc.
- Ưu tiên môn đúng/đã đến học kỳ gợi ý.

Kết quả trả về có các cột giải thích như `MucUuTien`, `DiemUuTien`, `LyDoGoiY`, `LyDoKhongGoiY`.

### 3. Hard/negative cases

Tạo thêm `production_hard_v04` để cover:

- Thiếu MSSV khi hỏi gợi ý.
- Mã/tên môn sai.
- Môn không tồn tại.
- Câu ngoài hệ thống.
- Câu mơ hồ như "môn nào nhẹ".
- "tôi còn thiếu môn gì".
- "kỳ sau thì sao".
- "nếu tôi không học CSDL kỳ này thì ảnh hưởng gì".
- Đổi context giữa nhiều sinh viên.

Files:

- `data/qwen_state_tracking_production_hard_v04.jsonl`
- `data/state_tracking_production_hard_eval_v04.jsonl`
- `data/production_hard_dialogues_v04.jsonl`
- `data/production_hard_quality_report_v04.json`
- `scripts/generate_production_hard_cases_v04.py`

### 4. Advisor/freeform gap data

Tạo thêm `advisor_gap_v03` để giảm thiếu hụt freeform:

- "kì này tôi nên đăng ký môn nào"
- "ki nay toi nen dang ky mon nao"
- "gợi ý môn phù hợp cho tôi"
- "tôi đã học những môn gì"
- "toi da hoc nhung mon gi"
- "hk này", "kì này", "học kỳ hiện tại"
- context quay lại phần gợi ý đăng ký

Files:

- `data/qwen_state_tracking_advisor_gap_train_v03.jsonl`
- `data/state_tracking_advisor_gap_eval_v03.jsonl`
- `data/advisor_gap_train_dialogues_v03.jsonl`
- `data/advisor_gap_eval_dialogues_v03.jsonl`
- `data/advisor_gap_quality_report_v03.json`
- `scripts/generate_advisor_gap_dataset_v03.py`

## Quality gates đã kiểm

Advisor gap v03:

- Không trùng câu train/eval.
- Không overlap với `qwen_state_tracking_train_v02`.
- Không duplicate full train input.
- Train/eval dùng tập sinh viên khác nhau.
- Eval row nào cũng có gold SQL/result.
- Có `COURSE_RECOMMENDATION`.

Production hard v04:

- Train states validate được bằng parser.
- Có missing required slot.
- Có invalid entity.
- Có out-of-scope.
- Có multi-student context.
- Có expected state và gold result cho eval.

## Vẫn cần team data bổ sung

Phần này không thể thay thế hoàn toàn real-user data. Team nên thu thêm 50-100 câu thật từ người dùng/sinh viên, nhất là:

- Cách hỏi tự nhiên không theo template.
- Câu hỏi mơ hồ, thiếu thông tin.
- Câu hỏi sai chính tả/không dấu.
- Câu hỏi đổi chủ đề nhiều lần.
- Câu hỏi advisor dài, có nhiều ràng buộc cá nhân.

Các câu thật đó nên được gán nhãn theo format:

```json
{
  "previous_state": {},
  "user_question": "...",
  "expected_state": {
    "intent": "...",
    "edit_operation": "...",
    "slots": {}
  },
  "gold_sql": "...",
  "expected_result": {}
}
```
