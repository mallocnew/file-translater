# 页译

在浏览器里翻译 PDF 和 Word。默认把原文件直接交给能阅读文档的模型，得到 Markdown 译文；也可以改用 Qwen-MT-Uni，尽量交回相同排版的 PDF 或 Word。

## 启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

也可以执行 `./run.sh`。打开 <http://127.0.0.1:8787>。

## 密钥

接口地址和 API Key 只在服务端配置。写在项目根目录的 `.env`：

```bash
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

密钥和接口地址要属于同一个地域。北京用 `dashscope.aliyuncs.com`，新加坡用 `dashscope-intl.aliyuncs.com`。业务空间地址写成 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。改完后重启服务。

## 模型

| 模型 | 能直接读的文件 | 结果 |
| --- | --- | --- |
| Qwen-Long | PDF、DOCX | Markdown，可再导出 Word / PDF |
| Qwen-Doc-Turbo | PDF、DOC、DOCX | Markdown，可再导出 Word / PDF |
| Qwen-MT-Uni | PDF、DOCX | 尽量保留原排版的 PDF 或 Word |

Qwen-Long / Qwen-Doc-Turbo 单文件上限 150 MB。Qwen-MT-Uni 单文件上限 100 MB、200 页，不支持旧版 DOC。它的语向比另外两款窄，例如日语目前只能译成英语；不支持的组合会在开始翻译时提示。

Qwen-MT-Uni 需要把文件先传到百炼临时存储，再异步翻译。请使用北京地域的密钥。译文文件会暂存在本地，可从页面下载。
