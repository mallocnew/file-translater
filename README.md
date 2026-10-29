# 页译

在浏览器里翻译 PDF 和 Word。原文件原样交给能直接阅读这两类文档的模型，本地不做格式转换、拆页或渲染。

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

文件上传到百炼后，用一次对话交给模型翻译。

| 模型 | 能直接读的文件 |
| --- | --- |
| Qwen-Long | PDF、DOCX |
| Qwen-Doc-Turbo | PDF、DOC、DOCX |

单文件上限 150 MB。上传到百炼的临时文件会在翻译结束后删除。

译文可以复制，或下载 Markdown 和 Word。
