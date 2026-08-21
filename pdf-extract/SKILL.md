---
name: pdf-extract
description: >-
  把 PDF 提取/转换成结构化的 markdown 或 json(供 LLM/RAG、检索、入库用)。覆盖:单个或整目录批量
  PDF 转 markdown、提取正文/标题/表格/阅读顺序、扫描件或图片版 PDF 做 OCR、要带 bounding box 的
  json 结构化输出。当用户说「把这个/这些 PDF 转成 markdown」「提取 PDF 里的文字/表格/结构」「PDF
  转结构化数据」「扫描的 PDF 识别成文本」「批量把目录里的 PDF 转 markdown」「parse/extract this
  PDF to markdown/json」「OCR this scanned PDF」时,**主动使用本 skill**,即使没点名工具。它会自动
  探测文字层选最优引擎并处理已知崩溃,比手搓 pdfminer/PyPDF 更可靠。注意区分:要「翻译」PDF 用
  pdf-translate;要「合并/拆分/填表单/加水印」用 pdf 技能;本 skill 专做正文结构提取。
---

# pdf-extract

把 PDF 转成干净的、适合喂大模型/做 RAG/入库的 **markdown 或 json**。难点不在"读 PDF",而在
**为每个 PDF 选对引擎**并扛住已知的坑——这套判断已固化进 `scripts/pdf_extract.py`,优先直接用它。

## 为什么不直接用 pdfminer / PyPDF
裸文本抽取会丢阅读顺序(多栏错位)、丢表格、对扫描件完全无效。本 skill:
- 带文字层的 PDF → **opendataloader-pdf 的 Local 模式**:确定性规则引擎,还原阅读顺序(XY-Cut)、
  标题层级、表格、bounding box,~60 页/秒,无需 GPU。绝大多数 PDF 走这条。
- 无文字层(扫描/图片版)→ **docling + EasyOCR**(默认含中文 `ch_sim`)。
- 自动识别 opendataloader 的两个静默崩溃并降级,保证仍有产出。

## 用法:跑脚本(首选)
```bash
python3 scripts/pdf_extract.py INPUT [INPUT ...] -o OUTDIR [options]
```
`INPUT` 可以是 `.pdf` 文件,也可以是目录(目录内所有 `*.pdf` 批量处理)。

常用例子:
```bash
# 单个文件转 markdown(输出到同目录)
python3 scripts/pdf_extract.py report.pdf

# 整个目录批量转,统一输出到一个文件夹
python3 scripts/pdf_extract.py ~/papers/ -o ~/papers/md

# 要带坐标的结构化 json
python3 scripts/pdf_extract.py invoice.pdf -f json

# 已知是扫描件 + 中日双语,4 进程并行 OCR 提速
python3 scripts/pdf_extract.py scan.pdf --mode ocr --ocr-lang ch_sim,japan,en --ocr-workers 4

# 文字版但不想要几千张插图,只要文本
python3 scripts/pdf_extract.py textbook.pdf --no-images
```

脚本会对每个 PDF 打印:页数、字符/页、选用的模式、产物路径与大小。读这些输出确认结果,失败的
文件会自动尝试降级路径。

## 选项速查
| 选项 | 作用 |
|---|---|
| `-f, --format` | `markdown`(默认)/`json`/`text`/`html`/`markdown-with-images`,可逗号多选 |
| `--mode` | `auto`(默认,探测文字层选路)/`local`/`ocr` |
| `--text-threshold` | 字符/页低于此值判为扫描件(默认 20) |
| `--no-images` | Local 模式不导出图片(也顺带绕开 raster bug) |
| `--ocr-lang` | EasyOCR 语言,逗号分隔(默认 `ch_sim,en`) |
| `--ocr-workers` | 扫描大文件并行 OCR 的进程数(默认 1;CPU OCR 慢,大文件设 4) |
| `--pages` | 页码范围,如 `5-12`(OCR 仅支持单段) |

## 依赖与首次安装
需要:Java(opendataloader 引擎)、`opendataloader-pdf`、`pymupdf`;OCR 还需 `docling`。
导入报错或首次使用时,运行:
```bash
bash scripts/setup.sh
```
它装好 JDK(经 brew)+ pip 包,并交互式询问是否装较大的 docling/OCR。脚本会自动探测
brew 的 openjdk 路径,所以一般无需手动改 PATH。

## 出问题时
脚本对每个 PDF 自动走 `local(图片开) → local(图片关) → docling OCR` 的降级链,多数情况无需干预。
要理解为什么这么设计、调 OCR 语言/并行、处理新出现的崩溃,或解释输出结构,读
[references/troubleshooting.md](references/troubleshooting.md)——里面有两个已知 opendataloader
崩溃的成因、OCR 调优、输出布局和格式选择。

## 边界(避免误用)
- **翻译** PDF(英→中保排版)→ 用 `pdf-translate`,不是本 skill。
- **合并/拆分/填表单/加水印/加密** PDF → 用 `pdf` 技能。
- 只是想**快速读一眼**某个小 PDF 的内容,直接读即可,不必动用本 skill。
