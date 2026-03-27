# Contact Only Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm `sales_mode` theo từng sản phẩm để một số sản phẩm customer chỉ thấy nhãn `Liên hệ` và bấm vào sẽ mở `@libi94`.

**Architecture:** Mở rộng bảng `products` với `sales_mode`, giữ flow mua hàng cũ cho `normal`, và branch customer list sang nút URL cho `contact_only`. Admin có thêm màn cấu hình `sales_mode` trong chi tiết sản phẩm.

**Tech Stack:** Python, sqlite3, pyTelegramBotAPI, unittest

---

### Task 1: Schema và service

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/database.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/repositories.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/services.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/test_database.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/test_services.py`

- [ ] Thêm cột `sales_mode`
- [ ] Viết test cập nhật `sales_mode`
- [ ] Implement repository/service

### Task 2: Customer flow

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/test_bot.py`

- [ ] Viết test cho label `Liên hệ`
- [ ] Viết test button URL `@libi94`
- [ ] Implement customer list branch `contact_only`

### Task 3: Admin flow

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/test_bot.py`

- [ ] Thêm màn cấu hình `sales_mode`
- [ ] Thêm callback cập nhật `normal/contact_only`
- [ ] Chạy targeted tests rồi full suite
