# ChatGPT Delivery Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Với sản phẩm ChatGPT, bot không gửi text tài khoản thô mà gửi file `.txt` 7 cột và thêm một block “copy nhanh” 4 cột.

**Architecture:** Giữ nguyên flow giao hàng hiện có, nhưng thêm một nhánh định dạng trong `send_delivered_order_messages()`: nhận diện sản phẩm ChatGPT, parse raw account thành các cột chuẩn, tạo file `.txt` trong bộ nhớ, rồi gửi thêm message Markdown cho thao tác copy nhanh.

**Tech Stack:** Python, io.BytesIO, pyTelegramBotAPI, unittest

---

### Task 1: Regression tests

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/test_bot.py`

- [ ] Thêm test cho ChatGPT delivery gửi document thay vì text thô
- [ ] Thêm test cho nội dung file `.txt`
- [ ] Thêm test cho block “copy nhanh”

### Task 2: Delivery helpers

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`

- [ ] Thêm helper nhận diện sản phẩm ChatGPT
- [ ] Thêm helper parse raw account thành 7 cột
- [ ] Thêm helper render file `.txt` và quick-copy block

### Task 3: Wiring và verify

**Files:**
- Modify: `C:/Users/PC/Documents/Project/telebot/bot.py`
- Modify: `C:/Users/PC/Documents/Project/telebot/test_bot.py`

- [ ] Nối nhánh ChatGPT vào `send_delivered_order_messages()`
- [ ] Giữ nguyên flow cũ cho sản phẩm không phải ChatGPT
- [ ] Chạy targeted tests rồi full suite
