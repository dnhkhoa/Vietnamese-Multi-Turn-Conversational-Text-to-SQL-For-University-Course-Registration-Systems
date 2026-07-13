# Bo cau hoi kiem tra on dinh UI + model 3B

## Flow can test

1. Portal UI goi `POST /api/chat`.
2. API goi `VietnameseNL2SQLEngine.ask(question)`.
3. Engine chay parser theo mode `hybrid`: Qwen 3B LoRA parse JSON state truoc, rule fallback neu model loi.
4. State gom `intent`, `edit_operation`, `slots`.
5. Engine merge voi context cau truoc neu la follow-up.
6. Engine chay SQL/view/business rule tren `data/ctdt_sis_v3.db`.
7. API tra `answer`, `rows`, `intent`, `edit_operation`, `slots`, `sql`, `parser_source`.

Account test chinh:

```text
MSSV: 22110001
Email: 22110001@hcmute.edu.vn
Password: Sv@22110001
```

## Smoke test login/UI

| ID | Cau hoi/thao tac | Ky vong |
|---|---|---|
| L01 | Dang nhap bang `22110001 / Sv@22110001` | Login OK, hien sinh vien Hoang Minh Mai |
| L02 | Dang nhap bang `22110001@hcmute.edu.vn / Sv@22110001` | Login OK |
| L03 | Dang nhap sai mat khau | Bao loi credential, khong vao portal |
| L04 | Mo chat, gui `cho toi xem cac lop hoc phan con cho` | API tra response, khong treo UI |

## Course offering search

| ID | Cau hoi | Ky vong |
|---|---|---|
| C01 | Cho toi xem cac lop mon CSDL | `COURSE_OFFERING_SEARCH`, `MaMH=DBSY230184E`, co lop Database System |
| C02 | Cho toi xem cac lop mon AI | `MaMH=ARIN330585E` |
| C03 | Lop mon thiet ke mang con cho khong? | `MaMH=CNDE430780E`, neu co `con cho` thi loc `CoTheDangKy=1` |
| C04 | Liet ke lop mon NLP hoc ky 2 nam 2026 | `MaMH=NLPR431585E`, `HocKy=2`, `NamHoc=2026` |
| C05 | Lop CSDL buoi sang con cho | Co slot `Buoi=SANG`, `CoTheDangKy=1` |
| C06 | Lop CSDL thu 2 tiet 1 den 5 | Co filter theo `Thu=2`, tiet |
| C07 | Sap xep lop con cho giam dan | Co `SortBy=SoChoCon`, `SortDirection=DESC` |
| C08 | Lay 5 lop dau thoi | `edit_operation=LIMIT`, toi da 5 dong |

## Schedule search

| ID | Cau hoi | Ky vong |
|---|---|---|
| S01 | Lich hoc mon Academic English 1 | `COURSE_SCHEDULE_SEARCH`, co cot thu/tiet/phong |
| S02 | Mon CSDL hoc phong nao? | Co thong tin phong neu co lich |
| S03 | Ai day lop Advanced Database? | Co `TenGV` |
| S04 | Lich lop LHP202610360 | Loc duoc dung lop neu parser lay `MaLHP` |
| S05 | Chi lay lich buoi chieu | Follow-up/loc `Buoi=CHIEU` |

## Course info

| ID | Cau hoi | Ky vong |
|---|---|---|
| I01 | Mon CSDL may tin chi? | `COURSE_INFO_SEARCH`, Database System, `SoTC=3` |
| I02 | Thong tin mon AI | Tra thong tin Artificial Intelligence |
| I03 | Mon NLP thuoc khoa/nganh nao? | Tra thong tin mon, khong nham sang sinh vien |
| I04 | Co nhung mon 3 tin chi nao? | Loc `SoTC=3` |

## Curriculum

| ID | Cau hoi | Ky vong |
|---|---|---|
| CT01 | Nganh CNTT co nhung mon bat buoc nao? | `CURRICULUM_COURSE_SEARCH`, `MaNganh=CNTT`, `LoaiYC=BAT_BUOC` |
| CT02 | Nganh CNTT co mon tu chon nao? | `LoaiYC=TU_CHON` |
| CT03 | Chi hoc ky 5 | Follow-up tren CTDT, giu `MaNganh=CNTT`, them `HocKy=5` |
| CT04 | Chuong trinh CNTT co mon CSDL khong? | Tra mon CSDL neu thuoc CTDT |

## Student info/profile

| ID | Cau hoi | Ky vong |
|---|---|---|
| SV01 | Thong tin sinh vien 22110001 | `STUDENT_INFO_LOOKUP`, dung Hoang Minh Mai |
| SV02 | Sinh vien 22110001 hoc nganh gi? | Tra `CNTT` |
| SV03 | Ho so hoc tap cua sinh vien 22110001 | `ACADEMIC_PROFILE_LOOKUP`, co GPA/tin chi |
| SV04 | Sinh vien 22110001 co bi canh bao hoc vu khong? | Co `CanhBaoHocVu`/ghi chu |
| SV05 | Tien do hoc tap cua sinh vien 22110001 | Co `TinChiTichLuy`, tong tin chi |

## Registration/result/credit

| ID | Cau hoi | Ky vong |
|---|---|---|
| R01 | Sinh vien 22110001 da dang ky nhung lop nao ky nay? | `STUDENT_REGISTRATION_LOOKUP`, co cac lop da dang ky |
| R02 | Sinh vien 22110001 da dang ky mon AI chua? | Loc theo sinh vien + mon |
| R03 | Sinh vien 22110001 dang ky bao nhieu tin chi? | `CREDIT_SUMMARY` |
| R04 | Ket qua hoc tap cua sinh vien 22110001 | `STUDENT_RESULT_LOOKUP` |
| R05 | Sinh vien 22110001 da dau mon CSDL chua? | Loc ket qua theo `MaMH=DBSY230184E` |
| R06 | Sinh vien 22110001 rot nhung mon nao? | Loc `KetQua=KHONG_DAT` |

## Eligibility/business rules

| ID | Cau hoi | Ky vong |
|---|---|---|
| E01 | Sinh vien 22110001 dang ky duoc lop LHP202620327 khong? | `REGISTRATION_ELIGIBILITY_CHECK`, `CoTheDangKy=1` |
| E02 | Sinh vien 22110001 dang ky duoc lop LHP202620300 khong? | `CoTheDangKy=0`, ly do `DA_DANG_KY_LOP_NAY` |
| E03 | Sinh vien 22110001 dang ky duoc mon NLP khong? | Tra danh sach lop/ly do theo mon |
| E04 | Sinh vien 25110292 dang ky duoc mon Mathematical Statistics for Engineers khong? | Scenario thieu tien quyet co the xuat hien ly do tien quyet |
| E05 | Sinh vien 24110445 dang ky duoc lop nao bi trung lich? | Scenario `TRUNG_LICH` |
| E06 | Sinh vien 22110155 dang ky them lop nao co vuot tin chi khong? | Scenario `VUOT_TIN_CHI` |

## Prerequisite

| ID | Cau hoi | Ky vong |
|---|---|---|
| P01 | Mon Introduction to Data Science can hoc truoc mon gi? | `PREREQUISITE_LOOKUP`, co Database System, Statistics, Programming techniques |
| P02 | Mon Network Design can hoc truoc mon gi? | Co Advanced Networking Technology/Networking Essentials |
| P03 | Mon nao yeu cau hoc CSDL truoc? | `PrereqDirection=REQUIRED_BY` |
| P04 | Sinh vien 22110001 con thieu tien quyet gi de hoc Mathematical Statistics for Engineers? | Neu thieu, tra danh sach mon tien quyet con thieu |

## Statistics

| ID | Cau hoi | Ky vong |
|---|---|---|
| ST01 | Moi mon co bao nhieu lop? | `AGGREGATION_STATISTICS`, co `SoLopHocPhan` |
| ST02 | Mon nao co nhieu sinh vien dang ky nhat? | Top 1/nhieu nhat |
| ST03 | Mon nao con nhieu cho nhat? | Thong ke `TongSoChoCon` |
| ST04 | Co bao nhieu sinh vien rot tung mon? | Thong ke `SoSinhVienKhongDat` |
| ST05 | Lay 5 dong dau thoi | Follow-up `LIMIT=5` |

## Multi-turn stability

Chay tung session rieng, khong refresh giua cac cau trong cung session.

| ID | Chuoi cau hoi | Ky vong |
|---|---|---|
| M01 | `Cho toi xem cac lop mon thiet ke mang` -> `Chi lay lop buoi sang con cho` -> `Doi sang mon AI` | Giu filter buoi sang/con cho khi doi mon |
| M02 | `Cho toi xem cac lop mon AI` -> `Mon nay can hoc truoc mon gi?` | Resolve `mon nay` thanh AI |
| M03 | `Nganh CNTT co nhung mon bat buoc nao?` -> `Chi hoc ky 5` | Giu nganh CNTT, them hoc ky 5 |
| M04 | `Moi mon co bao nhieu lop?` -> `Lay 5 mon dau thoi` | Giu intent thong ke, limit 5 |
| M05 | `Sinh vien 22110001 da dang ky nhung lop nao?` -> `Chi buoi sang` -> `Tong tin chi cua sinh vien nay?` | Resolve sinh vien nay = 22110001 |
| M06 | `Sinh vien 22110001 dang ky duoc lop LHP202620300 khong?` -> `Vay lop LHP202620327 thi sao?` | Doi entity lop, van eligibility |

## Negative/edge cases

| ID | Cau hoi | Ky vong |
|---|---|---|
| N01 | Cho toi xem mon khong ton tai ABCXYZ | Khong crash, co warning khong co dong phu hop |
| N02 | Sinh vien 99999999 da dang ky gi? | Khong crash, khong co dong |
| N03 | Dang ky duoc lop LHP202620327 khong? | Bao can ma sinh vien neu thieu `MaSV` |
| N04 | abc xyz random noise | Khong crash; neu fallback ve offering search thi co warning/rows hop ly |
| N05 | Reset chat/refresh roi hoi `mon nay can hoc truoc gi?` | Khong du context, khong duoc lay nham mon cu |
