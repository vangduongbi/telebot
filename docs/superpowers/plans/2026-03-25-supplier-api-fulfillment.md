# Supplier API Fulfillment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tích hợp supplier API cho các sản phẩm cấu hình `supplier_api`, có pre-check số dư trước khi tạo thanh toán và mua hàng thật sau khi customer thanh toán thành công.

**Architecture:** Mở rộng `products` với cấu hình fulfillment theo sản phẩm, thêm một client API riêng để gọi supplier, rồi branch flow mua hàng trong `bot.py`: `local_stock` giữ nguyên, `supplier_api` sẽ pre-check `balance + product detail` trước PayOS và gọi `buy` sau khi thanh toán thành công.

**Tech Stack:** Python, sqlite3, unittest, urllib, pyTelegramBotAPI

---

### Task 1: Schema và service theo sản phẩm

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/database.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/repositories.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/services.py`
- Test: `C:/Users/PC/Documents/Project/telebot/test_database.py`
- Test: `C:/Users/PC/Documents/Project/telebot/test_services.py`

- [ ] Thêm cột `fulfillment_mode` và `supplier_product_id` cho `products`
- [ ] Viết test cho lưu cấu hình supplier và hoàn tất đơn supplier không cần kho nội bộ
- [ ] Chạy targeted tests để thấy fail đúng nhánh mới
- [ ] Implement repository/service tối thiểu
- [ ] Chạy targeted tests lại

### Task 2: Supplier API client

**Files:**
- Create: `C:/Users/PC/Documents/Project/telebot/supplier_api.py`

- [ ] Tạo client GET balance, GET product detail, POST buy
- [ ] Chuẩn hóa lỗi thành `SupplierApiError`

### Task 3: Bot flow pre-check và fulfill

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`
- Test: `C:/Users/PC/Documents/Project/telebot/test_bot.py`

- [ ] Viết test đỏ cho pre-check balance và hoàn tất supplier order
- [ ] Chạy targeted tests để xác nhận fail đúng chỗ
- [ ] Thêm nhánh `supplier_api` trong `process_purchase`
- [ ] Thêm helper hoàn tất đơn sau thanh toán cho cả local và supplier
- [ ] Chạy full suite

### Task 4: Cấu hình sản phẩm tương lai

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`

- [ ] Thêm UI admin tối thiểu để đổi fulfillment mode và nhập `supplier_product_id`
- [ ] Giữ flow local stock cũ không đổi
