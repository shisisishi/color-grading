# -*- coding: utf-8 -*-
"""
serve.py — 本地调色工作台服务器

功能:
  1. 提供 index.html / css / js 静态文件 (这个项目的网页)
  2. /api/styles          : 返回可用风格列表给前端展示
  3. /api/process         : 接收上传图片 + style + params, 调用 grading.py 渲染, 返回成品
  4. /api/download        : 以附件形式下载渲染成品
  5. /check               : 健康检查

用法:
    python serve.py [端口]    # 默认 8033
    然后浏览器访问 http://127.0.0.1:8033

依赖只用到 Python 标准库: http.server, json, io, base64
图片解码/编码用 opencv (cv2) 或 Pillow 兜底。
"""
import io
import os
import sys
import json
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import numpy as np

import grading
from grading import STYLES

# 图片编解码优先 opencv, 其次 Pillow
try:
    import cv2

    def decode_image(data: bytes):
        buf = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)  # BGR
        if img is None:
            raise ValueError("无法解码图片")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float64) / 255.0
        return img

    def encode_image(img_float, fmt="jpg", quality=95):
        bgr = (img_float * 255.0).clip(0, 255).astype(np.uint8)
        bgr = cv2.cvtColor(bgr, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode("." + fmt, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise ValueError("编码失败")
        return buf.tobytes()

    BACKEND = "opencv"
except Exception:  # noqa: E722
    from PIL import Image

    def decode_image(data: bytes):
        im = Image.open(io.BytesIO(data)).convert("RGB")
        return np.asarray(im, dtype=np.float64) / 255.0

    def encode_image(img_float, fmt="jpg", quality=95):
        im = Image.fromarray((img_float * 255.0).clip(0, 255).astype(np.uint8))
        buf = io.BytesIO()
        im.save(buf, format="PNG" if fmt == "png" else "JPEG", quality=quality)
        return buf.getvalue()

    BACKEND = "pillow"


# 输出目录
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# 允许的静态文件路径(白名单, 防止任意目录读取)
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/css/style.css": ("css/style.css", "text/css; charset=utf-8"),
    "/js/app.js": ("js/app.js", "application/javascript; charset=utf-8"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
}

# 示例图库: name -> 文件名(在 samples/ 下的 jpg)
SAMPLE_DIR = os.path.join(BASE_DIR, "samples")
SAMPLES = [
    {"name": "demo_gradient", "label": "合成渐变"},
    {"name": "demo_shapes", "label": "合成色块"},
]


def style_list():
    return [
        {"key": k, "name": v[0], "desc": v[2]}
        for k, v in STYLES.items()
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "GradingWorkbench/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # -------------------- 工具 --------------------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, relpath, ctype):
        full = os.path.join(BASE_DIR, relpath)
        if not os.path.isfile(full):
            self._send_json({"error": "not found"}, 404)
            return
        with open(full, "rb") as f:
            data = f.read()
        self._send_bytes(data, ctype)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(length)

    # -------------------- GET --------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/check":
            self._send_json({
                "ok": True,
                "backend": BACKEND,
                "styles": len(STYLES),
                "styles_list": list(STYLES.keys()),
            })
            return
        if path == "/api/styles":
            self._send_json({"styles": style_list()})
            return
        if path == "/api/samples":
            self._send_json({"samples": SAMPLES})
            return
        if path.startswith("/samples/"):
            name = path[len("/samples/"):].split(".")[0]
            full = os.path.join(SAMPLE_DIR, name + ".jpg")
            if name in {item["name"] for item in SAMPLES} and os.path.isfile(full):
                with open(full, "rb") as f:
                    self._send_bytes(f.read(), "image/jpeg")
            else:
                self._send_json({"error": "sample not found", "name": name}, 404)
            return
        if path in STATIC_FILES:
            rel, ctype = STATIC_FILES[path]
            self._send_file(rel, ctype)
            return
        # 兜底: 尝试在 BASE_DIR 下找 (仅限已知子目录 css/js)
        self._send_json({"error": "not found", "path": path}, 404)

    # -------------------- POST --------------------
    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/process":
            self._handle_process()
        elif path == "/api/autograde":
            self._handle_autograde()
        elif path == "/api/download":
            self._handle_download()
        else:
            self._send_json({"error": "not found", "path": path}, 404)

    def _handle_autograde(self):
        """智能自动修图: 分析图片 -> 推荐风格 + 参数 -> 直接渲染成品"""
        try:
            body = self._read_body()
            if not body:
                self._send_json({"error": "空请求体"}, 400)
                return
            payload = json.loads(body.decode("utf-8"))
            img_b64 = payload.get("image", "")
            image_bytes = base64.b64decode(img_b64)
            img = decode_image(image_bytes)
            rec = grading.auto_grade(img)
            out = grading.apply_style(img, rec["style"], rec["params"])
            out_bytes = encode_image(out, fmt="png")
            result_b64 = base64.b64encode(out_bytes).decode("ascii")
            self._send_json({
                "ok": True,
                "style": rec["style"],
                "name": rec["name"],
                "params": rec["params"],
                "reason": rec["reason"],
                "features": rec["features"],
                "backend": BACKEND,
                "width": int(img.shape[1]),
                "height": int(img.shape[0]),
                "image": result_b64,
            })
        except Exception as e:  # noqa: E722
            self._send_json({"error": str(e), "trace": __import__("traceback").format_exc()}, 500)

    def _handle_process(self):
        try:
            body = self._read_body()
            if not body:
                self._send_json({"error": "空请求体"}, 400)
                return
            # JSON: { image: base64, style: "japan", params: {...} }
            payload = json.loads(body.decode("utf-8"))
            img_b64 = payload.get("image", "")
            style = payload.get("style", "original")
            params = payload.get("params") or {}
            if not params:
                params = {}
            image_bytes = base64.b64decode(img_b64)
            img = decode_image(image_bytes)
            out = grading.apply_style(img, style, params)
            # 编码为 PNG(无损)保证质量, 前端可直接预览+下载
            out_bytes = encode_image(out, fmt="png")
            result_b64 = base64.b64encode(out_bytes).decode("ascii")
            self._send_json({
                "ok": True,
                "style": style,
                "backend": BACKEND,
                "width": int(img.shape[1]),
                "height": int(img.shape[0]),
                "image": result_b64,
            })
        except Exception as e:  # noqa: E722
            self._send_json({"error": str(e), "trace": __import__("traceback").format_exc()}, 500)

    def _handle_download(self):
        # POST /api/download { image: base64, name: "xxx.png" }
        try:
            body = self._read_body()
            payload = json.loads(body.decode("utf-8"))
            img_b64 = payload.get("image", "")
            name = payload.get("name", "graded.png")
            image_bytes = base64.b64decode(img_b64)
            data = image_bytes  # 前端已传回 PNG 字节
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: E722
            self._send_json({"error": str(e)}, 500)


def main():
    port = 8033
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("=" * 60)
    print(" 调色工作台已启动")
    print(" 地址: http://127.0.0.1:%d" % port)
    print(" 风格数: %d | 图像后端: %s" % (len(STYLES), BACKEND))
    print(" 按 Ctrl+C 停止")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.server_close()


if __name__ == "__main__":
    main()

