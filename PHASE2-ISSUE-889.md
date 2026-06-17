# CodePath AI301 — Phase II: Reproduce & Plan

**Project:** OpenAlgo  
**Issue:** [#889 — frontend: Improve empty state UI with icons and consistent pattern](https://github.com/marketcalls/openalgo/issues/889)  
**Upstream repo:** https://github.com/marketcalls/openalgo  
**Fork:** https://github.com/kietcoderlor/openalgo  
**Branch:** `fix-889-empty-state-ui`  
**Author:** kietcoderlor  
**Date:** 2026-06-09  

---

## Mục tiêu Phase II

Phase II **không cần mở Pull Request**. Chỉ cần:

1. Setup và hiểu project local
2. Reproduce / verify issue empty state UI không nhất quán
3. Xác định file liên quan và pattern hiện tại
4. Viết reproduction steps + implementation plan (file này dùng cho Contribution README)

---

## Tiến độ Phase II

| Hạng mục | Trạng thái | Ghi chú |
|----------|------------|---------|
| Clone fork & tạo branch | ✅ Done | `fix-889-empty-state-ui` |
| Đọc issue #889 | ✅ Done | Scope: `MarketTimings.tsx`, `Search.tsx` |
| Phân tích reference pattern | ✅ Done | `StrategyIndex.tsx` |
| Phân tích empty state hiện tại | ✅ Done | Plain text / minimal UI |
| Setup môi trường local (Windows) | ✅ Done | Xem mục Setup bên dưới |
| Chạy backend + frontend | ✅ Done | Port 5000 + 5173 |
| Reproduce trên browser + screenshots | ⬜ Cần làm | Xem checklist cuối file |
| Implementation plan | ✅ Done | Xem mục Implementation Plan |
| Phase III — sửa code | ⬜ Chưa làm | Sau khi hoàn thành Phase II |

---

## Những gì đã làm

### 1. Khám phá codebase

**Reference pattern (chuẩn cần theo):** `frontend/src/pages/strategy/StrategyIndex.tsx`

Khi không có data, page dùng:

- `Card` bọc ngoài (`py-12`)
- Layout căn giữa: icon → heading → description → optional CTA button
- Icon từ `lucide-react` (`h-12 w-12 text-muted-foreground`)
- Pattern này cũng được document trong `frontend/docs/frontend/components.md` (mục **Empty States**)

**Các page cần cải thiện (theo issue):**

| File | Vấn đề hiện tại |
|------|-----------------|
| `frontend/src/pages/admin/MarketTimings.tsx` | Hai chỗ chỉ hiện plain text muted: "Markets are closed today..." và "Markets are closed on {date}..." |
| `frontend/src/pages/Search.tsx` | Table cell chỉ hiện `"No results found"` hoặc error text đỏ — không có icon, heading, CTA |

**Routes liên quan** (`frontend/src/App.tsx`):

- `/strategy` → StrategyIndex (reference)
- `/admin/timings` → MarketTimings
- `/search` → Search results
- `/search/token` → Search form (điểm bắt đầu để trigger empty results)

### 2. Setup local trên Windows

**Prerequisites đã cài / dùng:**

- Node.js v22.22.0, npm 11.6.2
- `uv` (package manager Python) — cài qua https://astral.sh/uv/
- Python 3.12.13 (uv tự tải, vì repo yêu cầu `>=3.12`)

**Backend:**

```powershell
cd D:\openalgo
copy .sample.env .env
# Sửa .env (xem mục Cấu hình .env)
C:\Users\ADMIN\.local\bin\uv.exe sync
D:\openalgo\.venv\Scripts\python.exe app.py
```

→ Backend: **http://localhost:5000**

**Frontend:**

```powershell
cd D:\openalgo\frontend
npm install
npm run dev
```

→ Frontend: **http://localhost:5173** (dùng `localhost`, không phải `127.0.0.1` — Vite bind IPv6 trên máy test)

**Package manager & scripts chính:**

| Tool | Lệnh |
|------|------|
| npm | `npm install`, `npm run dev`, `npm run build`, `npm run lint` |
| uv | `uv sync`, `uv run app.py` |

### 3. Cấu hình `.env` đã chỉnh (local dev)

File `.env` **không commit** (gitignored). Đã thay đổi để backend khởi động được:

| Biến | Giá trị | Lý do |
|------|---------|-------|
| `REDIRECT_URL` | `http://127.0.0.1:5000/zerodha/callback` | App refuse start nếu còn placeholder `<broker>` |
| `FLASK_DEBUG` | `'True'` | Dev trên `127.0.0.1`; tránh lỗi Werkzeug khi `False` |

Lần chạy đầu, OpenAlgo tự generate `APP_KEY` và `API_KEY_PEPPER`.

### 4. Lưu ý khi dev frontend

Vite proxy (`frontend/vite.config.ts`) chỉ forward:

- `/api/*` → port 5000
- `/auth/*` → port 5000
- `/socket.io/*` → port 5000

**Không proxy:** `/search/api/*`, `/admin/api/*`

→ Để test Search và Market Timings đầy đủ, nên dùng **http://localhost:5000** (sau `npm run build`) hoặc đảm bảo backend đang chạy khi dùng port 5173.

---

## Reproduction Steps

### Setup (một lần)

1. Checkout branch `fix-889-empty-state-ui`
2. Copy `.sample.env` → `.env`, cấu hình như mục trên
3. `uv sync` (root) và `npm install` (frontend)
4. Chạy backend (port 5000) + frontend dev (port 5173) hoặc `npm run build` + chỉ backend
5. Mở http://localhost:5000 — hoàn tất `/setup` nếu lần đầu, đăng nhập **admin** (cần cho `/admin/timings`)

### A. Reference — empty state tốt (`StrategyIndex`)

1. Vào **http://localhost:5173/strategy** (hoặc :5000/strategy)
2. Đảm bảo **không có webhook strategy** nào
3. **Kỳ vọng (đúng pattern):**
   - Icon `Zap`
   - Heading: "No Strategies Yet"
   - Mô tả + nút "Create Strategy"

📸 **Screenshot cần chụp:** empty state Strategy (reference)

### B. Bug — `MarketTimings.tsx`

1. Vào **http://localhost:5173/admin/timings**
2. **Panel "Today's Timings":**
   - Vào **cuối tuần** hoặc ngày nghỉ → `todayTimings` rỗng
   - **Kỳ vọng (issue):** Chỉ một dòng text muted, không icon/heading
3. **Panel "Check Timings for Date":**
   - Chọn **thứ Bảy** (vd. `2026-06-06`) hoặc ngày lễ
   - Bấm **Check**
   - **Kỳ vọng (issue):** Plain text "Markets are closed on {date} (Weekend/Holiday)"

📸 **Screenshot cần chụp:** cả hai empty state Market Timings

### C. Bug — `Search.tsx`

1. Vào **http://localhost:5173/search/token**
2. Tìm symbol không tồn tại, vd. `ZZZNOMATCH999`
3. Submit → redirect tới `/search?symbol=ZZZNOMATCH999`
4. **Kỳ vọng (issue):** Trong table chỉ có chuỗi `"No results found"` — không icon, heading, CTA

📸 **Screenshot cần chụp:** Search results empty state

### So sánh nhanh

| Page | Route | Trigger | UI hiện tại | UI mong muốn |
|------|-------|---------|-------------|--------------|
| Strategy Index | `/strategy` | Không có strategy | Icon + heading + CTA | ✅ Reference |
| Market Timings | `/admin/timings` | Weekend/holiday | Plain text | Icon + heading + description |
| Search Results | `/search?symbol=...` | Không có kết quả | Plain string trong table | Icon + heading + description + optional CTA |

---

## Implementation Plan (Phase III)

> **Phase II chỉ lập kế hoạch — chưa sửa code.**

### Nguyên tắc

- Giữ diff nhỏ, inline JSX giống `StrategyIndex.tsx` (issue estimate 30–45 phút)
- Dùng `lucide-react` icons có ngữ cảnh
- Không refactor lớn trừ khi maintainer yêu cầu shared component

### `MarketTimings.tsx` — 2 empty states

**Vị trí:** "Today's Timings" (~line 261) và "Check Timings for Date" (~line 310)

**Thay plain `<div>` bằng:**

- Icon: `CalendarOff` hoặc `CalendarX`
- Heading: `"Markets Closed"`
- Description: giữ nguyên copy hiện có (có `{checkDate}` ở panel thứ hai)
- Không cần CTA (informational)

### `Search.tsx` — table empty state

**Vị trí:** `TableBody` khi `paginatedResults.length === 0` (~line 475)

**No results:**

- Icon: `SearchX`
- Heading: `"No Results Found"`
- Description: gợi ý thử symbol/filter khác
- Optional CTA: `Button` link tới `/search/token` — "New Search"

**Error state:**

- Giữ màu destructive nhưng thêm cấu trúc: `AlertTriangle` + heading `"Search Failed"` + message

### QA sau khi sửa (Phase III)

- [ ] Re-run reproduction steps A–C
- [ ] So sánh visual với `/strategy`
- [ ] Test light / dark theme
- [ ] `npm run lint` trong `frontend/`

### Files dự kiến sửa (Phase III)

| File | Thay đổi |
|------|----------|
| `frontend/src/pages/admin/MarketTimings.tsx` | 2 empty states |
| `frontend/src/pages/Search.tsx` | Empty + error trong table |
| `frontend/src/pages/strategy/StrategyIndex.tsx` | Optional — chỉ nếu tạo shared component |

**Không cần sửa:** backend Python, routes `App.tsx`, API modules.

---

## Bạn cần làm gì tiếp để hoàn thành Phase II?

Phase II coi là **xong** khi bạn có đủ 4 phần sau (3 phần đã có trong file này, 1 phần cần bạn tự làm trên browser):

### ✅ Đã xong (có thể copy vào Contribution README)

1. **Mô tả issue** và file liên quan
2. **Setup instructions** (Windows + npm + uv)
3. **Reproduction steps** chi tiết
4. **Implementation plan** cho Phase III

### ⬜ Còn lại — bạn cần tự hoàn thành

1. **Reproduce trên browser** theo steps A–C ở trên
2. **Chụp 3–4 screenshots:**
   - Strategy empty state (reference, tốt)
   - Market Timings — Today's Timings (plain text)
   - Market Timings — Check Date (plain text)
   - Search — "No results found"
3. **Nộp Contribution README** lên CodePath (copy các mục: Issue Summary, Setup, Reproduction, Screenshots, Implementation Plan từ file này)
4. **(Tuỳ chọn)** Commit file này lên fork để lưu tiến độ:
   ```powershell
   git add PHASE2-ISSUE-889.md
   git commit -m "docs: Phase II reproduce & plan for issue #889"
   git push origin fix-889-empty-state-ui
   ```

### Phase III (sau Phase II)

- Implement thay đổi theo Implementation Plan
- Mở PR lên `marketcalls/openalgo` referencing #889

---

## Tài liệu tham khảo

- Issue: https://github.com/marketcalls/openalgo/issues/889
- Empty state pattern doc: `frontend/docs/frontend/components.md`
- Dev guide: `frontend/docs/frontend/developer-guide.md`
- Full stack dev: `docs/design/35-development-testing/README.md`
