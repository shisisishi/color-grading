# 调色学习站与修图工作台

本地图片调色工具，包含调色知识库、12 种风格、手动参数和自动推荐。图片处理在本机执行，无需 API 密钥。发布版仅提供代码生成的渐变与色块示例，未包含私人照片、软件安装包或旧输出。

## 运行

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python serve.py 8033
```

访问 http://127.0.0.1:8033/ ，选示例或本地照片，选风格并渲染、下载。NumPy 实现调色；Pillow 编解码，已安装 OpenCV 时优先使用它。

## 验证与限制

`python verify.py` 会启动临时本地服务，实际调用健康检查、全部风格渲染、自动推荐与下载接口，并检查返回的 PNG 尺寸。自动推荐是图像统计规则，效果需用户判断。此项目依赖 Python 后端，GitHub Pages 无法运行修图接口。服务只绑定本机回环地址；大尺寸图片会占用较多内存。
