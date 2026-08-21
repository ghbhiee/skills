---
name: pdf-translate
description: >-
  保留排版地翻译 PDF 文献（默认英→中）：直接解析 PDF，按版面结构逐块提取文字，送 LLM
  （默认 DeepSeek）翻译后按原坐标回填，保留文字颜色/样式，连表格、流程图/图内文字也翻译，
  公式 / 图片整块原样保留；先自动抽取术语表保证缩写一致、不胡乱展开（如 MI 按上下文判为
  密歇根州而非心肌梗死）。输出纯译文版（.mono.pdf）、中英对照版（.dual.pdf）和术语表
  （.glossary.csv）。底层默认 BabelDOC 引擎，可回退 pdf2zh。当用户说「翻译这个 PDF」
  「把这篇论文/文献翻译成中文」「PDF 翻译保留排版」「翻译英文文献」「translate this pdf」
  「translate this paper to Chinese」时触发。需要本机 DeepSeek key（交互式 zsh 的
  DEEPSEEK_API_KEY，脚本自动取）。
---

# PDF 文献翻译（保留排版 · 翻表格/流程图 · 术语一致）

直接解析 PDF → DocLayout 版面分析 → **自动抽取全文术语表**（缩写按上下文判定）→ 逐块翻译
（保留文字颜色/样式，表格单元格、流程图框内文字一并翻）→ 按原坐标回填，公式/图片原样保留。
输出三份：纯译文 `*.mono.pdf`、中英对照 `*.dual.pdf`（默认**交替页**：一页原文、一页译文，适合打印；
加 `--side-by-side` 改回左右并排同页）、术语表 `*.glossary.csv`。

底层默认 **[BabelDOC](https://github.com/funstory-ai/BabelDOC)** 引擎（命令 `babeldoc`，
中间表示重排，比 pdf2zh 原版在颜色/表格/流程图/版面重叠上都更好），翻译后端 **DeepSeek**
（OpenAI 兼容）。可用 `--engine pdf2zh` 回退到原版 pdf2zh。

> 为什么不是原版 pdf2zh：原版会把文字**颜色重置为黑**、把**表格/流程图当 figure 整块跳过**、
> 中文比英文长时**行重叠**、且逐块翻译**无上下文**导致缩写乱译。BabelDOC 逐一解决了这些。

## 用法

都走 `scripts/pdf-translate.sh`（自动取 DeepSeek key、建输出目录、设好上面那套默认值）：

```bash
# 默认：英→中，BabelDOC，翻表格+流程图，关水印，自动术语表，输出到源文件旁 translated/
~/.claude/skills/pdf-translate/scripts/pdf-translate.sh "/path/to/paper.pdf"

# 给文档背景（强烈建议，进一步压住缩写乱译）
~/.claude/skills/pdf-translate/scripts/pdf-translate.sh \
  --context "review on anticoagulation of new-onset atrial fibrillation after cardiac surgery" \
  "/path/to/paper.pdf"

# 先翻前 3 页试效果，省 token
~/.claude/skills/pdf-translate/scripts/pdf-translate.sh -p 1-3 "/path/to/paper.pdf"

# 自定义术语表，强制某些缩写保留英文/指定译法（CSV: source,target,tgt_lng）
~/.claude/skills/pdf-translate/scripts/pdf-translate.sh --glossary terms.csv "/path/to/paper.pdf"

# 批量
~/.claude/skills/pdf-translate/scripts/pdf-translate.sh a.pdf b.pdf c.pdf
```

参数（都有默认值，通常只给 PDF 路径，最多再加 `--context`）：

| 参数 | 含义 | 默认 |
|------|------|------|
| `-li/-lo` | 源/目标语言 | `en` / `zh` |
| `-p` | 页码范围 `1-3` / `1,3,5` | 全文 |
| `-o` | 输出目录 | 源文件同级 `translated/` |
| `--engine` | `babeldoc` / `pdf2zh` | `babeldoc` |
| `--context` | 文档背景，附加进 system prompt | 无 |
| `--glossary` | 自定义术语表 CSV | 无（仅用自动抽取） |
| `--model` / `--base-url` | DeepSeek 模型 / 端点 | `deepseek-chat` / `https://api.deepseek.com` |
| `--qps` | 速率上限 | `4` |
| `--no-table` | 不翻表格 | 翻 |
| `--side-by-side` | dual 改成左右并排同页 | 默认**交替页**(一页原文/一页译文,适合打印) |
| `--keep-watermark` | 保留 BabelDOC 水印 | 去掉 |

## 工作流程（给 Claude 的提示）

1. **先确认语言方向。** 文件名可能误导（中文名也可能是英文正文）。不确定先看一眼正文，默认 `en→zh`。
2. **能给背景就给 `--context`。** 一句话主题（学科/疾病/方法）能显著减少缩写和歧义词误译。
3. **长文献先 `-p 1-3` 试。** 看版面/术语满意再翻全文，省 DeepSeek 额度。
4. **跑完渲染验证。** 用 `uv run --with pymupdf python` 把 `*.mono.pdf` 关键页渲成 PNG
   （`get_pixmap(dpi=100)`）自查：作者块有无重叠、彩色标题颜色在不在、表格/流程图翻没翻，再交付。
5. **交付。** 用 SendUserFile 发 `*.mono.pdf`（纯译文）+ `*.dual.pdf`（对照）+ `*.glossary.csv`（术语表）。
6. **扫描件/图片型 PDF（无文字层）** 走 OCR 路线，BabelDOC 这条不灵，提示用户改 RetainPDF 或先 OCR。

## 注意

- **首次运行**会下 DocLayout ONNX 模型 + 整套思源/Noto 字体（CN/TW/HK，约一两百 MB），属正常、仅一次。
- **DeepSeek key**：脚本用 `zsh -ic` 从交互式 zsh 取 `DEEPSEEK_API_KEY`（非交互 shell 取不到）。
  取不到就提示在 `~/.zshrc` 里 `export DEEPSEEK_API_KEY=...`。
- **耗时**：BabelDOC 比 pdf2zh 多一步「全文术语抽取」，7 页论文约 2~3 分钟、token 略多但术语更一致。
- **Mac GPU**：BabelDOC 用 CoreML 跑版面分析。**网络**：本机 Clash TUN 透明代理，无需设 HTTPS_PROXY。
- 已安装：`babeldoc`（本体）、`pdf2zh`（fallback），均在 `~/.local/bin`（uv tool）。
