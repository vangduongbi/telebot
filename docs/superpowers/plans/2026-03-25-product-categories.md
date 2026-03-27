# Product Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm category do admin quản lý để customer đi theo luồng danh mục → sản phẩm, kèm nút `Tất cả sản phẩm`.

**Architecture:** Mở rộng SQLite với bảng `categories` và cột `products.category_id`, thêm repository/service mỏng cho category, rồi đổi `bot.py` sang hai lớp điều hướng mới: customer chọn danh mục trước và admin tạo/gán category cho sản phẩm.

**Tech Stack:** Python, sqlite3, pyTelegramBotAPI, unittest

---

### Task 1: Schema và Repository

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/database.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/repositories.py`
- Test: `C:/Users/PC/Documents/Project/telebot/test_database.py`

- [ ] Viết test đỏ cho bảng `categories` và cột `products.category_id`
- [ ] Chạy test để xác nhận fail đúng chỗ
- [ ] Thêm schema/upgrade path cho DB hiện có
- [ ] Thêm repository CRUD tối thiểu cho category và gán sản phẩm vào category
- [ ] Chạy test lại

### Task 2: Service Layer

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/services.py`
- Test: `C:/Users/PC/Documents/Project/telebot/test_services.py`

- [ ] Viết test đỏ cho tạo category, gán sản phẩm vào category, lọc sản phẩm theo category
- [ ] Chạy test để xác nhận fail đúng chỗ
- [ ] Thêm service methods tối thiểu
- [ ] Chạy test lại

### Task 3: Bot Flow

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`
- Test: `C:/Users/PC/Documents/Project/telebot/test_bot.py`

- [ ] Viết test đỏ cho customer flow category → product và admin flow tạo/gán category
- [ ] Chạy test để xác nhận fail đúng chỗ
- [ ] Cập nhật `/start` / `Danh sách sản phẩm` sang danh mục trước
- [ ] Thêm admin UI tạo category và gán category cho sản phẩm
- [ ] Chạy targeted tests rồi full suite
