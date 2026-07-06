# Hướng dẫn Triển khai & Cài đặt FourTIndex MCP ở Máy khác

Tài liệu này hướng dẫn cách đóng gói dự án `FourTIndex`, copy và cài đặt sang máy tính khác (hoặc môi trường làm việc khác) để chạy MCP server toàn cục.

---

## Bước 1: Build file đóng gói (Wheel)
Trên máy tính hiện tại (hoặc máy phát triển):
1. Nhấp đúp chuột vào file `build_dist.bat` (hoặc mở Terminal tại thư mục gốc và chạy lệnh `./build_dist.bat`).
2. Script sẽ tự động nâng cấp các công cụ đóng gói và tạo các file nén trong thư mục `dist/`.
3. Tìm file có đuôi `.whl` (ví dụ: `dist/fourtindex-0.1.0-py3-none-any.whl`).

---

## Bước 2: Cài đặt trên máy tính khác (bên khác)
1. Copy file `.whl` đã build ở Bước 1 sang máy tính đích.
2. Mở Terminal (Command Prompt hoặc PowerShell trên Windows) tại thư mục chứa file `.whl`.
3. Chạy lệnh cài đặt:
   ```bash
   pip install fourtindex-0.1.0-py3-none-any.whl
   ```
   *(Lưu ý: Thay đổi tên file `.whl` cho đúng với phiên bản thực tế nếu có thay đổi).*

---

## Bước 3: Xác minh cài đặt CLI
Sau khi cài đặt xong, lệnh CLI `fourtindex` sẽ khả dụng toàn cục trên hệ thống. 
Thử chạy lệnh sau từ một thư mục bất kỳ (ví dụ: Desktop):
```bash
fourtindex --help
```

> [!NOTE]
> **Khởi tạo lần đầu:**
> Trong lần chạy đầu tiên, chương trình sẽ tự động copy file cấu hình mặc định vào thư mục cá nhân của người dùng tại đường dẫn:
> `~/.fourtindex/config.yaml` (ví dụ: `C:\Users\<Tên_User>\.fourtindex\config.yaml` trên Windows).
> Toàn bộ cơ sở dữ liệu vector DB cũng sẽ được tạo tại `~/.fourtindex/db/`.

---

## Bước 4: Tích hợp MCP vào Editor

### 1. Tích hợp vào Claude Desktop (Windows)
1. Mở hoặc tạo file cấu hình Claude Desktop tại đường dẫn:
   `%APPDATA%\Claude\claude_desktop_config.json`
2. Thêm `fourtindex` vào danh sách `mcpServers`:
   ```json
   {
     "mcpServers": {
       "fourtindex": {
         "command": "fourtindex",
         "args": ["mcp"]
       }
     }
   }
   ```
3. Khởi động lại ứng dụng Claude Desktop.

### 2. Tích hợp vào Cursor
1. Mở Cursor, truy cập **Settings > Features > MCP**.
2. Nhấp vào nút **+ Add New MCP Server**.
3. Điền thông tin cấu hình:
   - **Name:** `fourtindex`
   - **Type:** `command` hoặc `stdio`
   - **Command:** `fourtindex mcp`
4. Nhấp **Save**.

---

## Bước 5: Index dự án và sử dụng
1. Để index (quét mã nguồn) của một dự án bất kỳ, mở terminal tại thư mục dự án đó và chạy:
   ```bash
   fourtindex index . --project-name "TenDuAnCuaBan"
   ```
2. Sau khi index thành công, các AI Assistant trong Claude Desktop hoặc Cursor sẽ tự động sử dụng các MCP tools của `fourtindex` để đọc outline, tìm kiếm mã nguồn và hiểu cấu trúc dự án của bạn!
