# Token 消耗与账单对账（0.9.0）

本模块可脱离 Codex 独立运行，不需要另配大模型。它使用协议解析、可复现计算、账单匹配及可选本机 OCR。Token 甲乙丙丁戊只表示相对消耗量，与能力 S/A/B/C/D 分开。

## 普通使用

1. 双击 start.cmd（个人版也可双击“启动中转模型检测.cmd”），填中转地址、所选型号、Key。建议新建一个专用测试 Key，以隔离记录；这不是强制要求。
2. 回车开始原来的 16 题快检。默认不新增付费模型调用，自动记录每次请求时间、请求 ID、接口用量、独立输入估算。Chat 流式请求会请求最终 usage；旧网关拒绝 stream_options 时可显式传 `--no-stream-usage` 保留原请求格式。
3. 采集正常完成后自动尝试同站 New API 的只读 `/api/log/token`。不支持、权限不足或近期窗口未覆盖时，结果会说明；超时中止的快检不额外等待账单查询。
4. 自动打开本机“Token 核账”页面。可以沿用本次 Key 查询账单，也可以输入站点提供的单独只读查询凭据；凭据只留在进程内存中。
5. 查询不了就拖入整个 CSV / TSV / JSON / NDJSON 文件，或粘贴完整导出文字。支持常见中英文列名、New API JSON、合并的 `输入 / 输出` Tokens 列。无需手动选字段。
6. 截图优先使用 Windows 自带 OCR；其他系统可使用已安装的 Tesseract。识别文字和表格只在本机处理。识别结果需核对时显示可编辑表格；不可靠的数字不会直接参与核账。看不清的小字号、压缩图片、未知布局仍可能需要导出文件。
7. 新增对账写入原报告旁的 `*-billing.json` 和同名 HTML，保留原报告。页面“关闭本机服务”可结束核账服务，静态报告继续可用。

已有报告可重新打开：

```sh
python run_relaylens.py --billing-ui reports/example.json
```

命令行离线导入，不调用模型：

```sh
python run_relaylens.py --compare-report reports/example.json --bill-file bill.csv --out reports/example-checked.json --html-out reports/example-checked.html
```

`--no-billing-auto` 可关闭自动账单查询；所有高级检测入口保持可用。自动查询只适配已知的只读接口，不能通用登录任意后台，也不会读取浏览器 Cookie。自定义查询凭据通过请求头发送，不能放在网址内。

## 看懂四种数字

- **接口上报**：中转响应的 usage。它可以被中转修改。
- **独立输入计数**：默认本机估算；有适配的 tiktoken 时使用对应编码，但仍不把 JSON 序列化估算说成精确协议计数。未知新模型不会静默套用旧模型 tokenizer。
- **后台账单**：按请求 ID 优先匹配；没有对应 ID 时，只接受时间与型号互相唯一的匹配。并发冲突不随意分配，也不使用“Token 数相同”作为匹配条件来掩盖倍率。显示输入、输出、缓存的差额与比值、覆盖率及已匹配金额。
- **官方同题参考**：独立的官方直连 RelayLens 报告。导入前应自行核实来源；本软件无法认证一份 JSON 的真实来源。

接口与账单相同只能证明两处记录一致。完整上游提示词和隐藏推理不可见，RelayLens 不能保证还原所有真实耗费，也不会让被测模型自报 token 作为证据。余额差额有其他 Key 消费时也不能自动归属本轮。

## 独立计数和输入倍率

可选安装本机 tokenizer：`python -m pip install "relaylens[tokenizer]"`（从本地源码安装时使用 `python -m pip install ".[tokenizer]"`）。没有安装也能完成原有检测和账单导入。

如自己有官方 API Key，可在运行环境中设置一个自定名称的环境变量，例如 `OFFICIAL_COUNTER_KEY`，再传：

```sh
python run_relaylens.py --base-url https://relay.example/v1 --model gpt-6.1-sol --target-model gpt-6.1-sol --mode fast --official-count-key-env OFFICIAL_COUNTER_KEY --token-probes 6
```

中转 Key 仍在隐藏提示中输入或通过 `RELAYLENS_API_KEY` 提供。官方 Key 只发送到官方域名的计数接口，不发送给中转，不写入报告。OpenAI Responses 使用 `/v1/responses/input_tokens`；Claude Messages 使用 `/v1/messages/count_tokens`，Claude 官方计数也保留估算性质。Chat Completions 不冒充支持精确官方计数。仅复制官方 Key 到中转输入框不能获得独立证据。

`--token-probes 6` 是明确选择的 6 次额外付费输入长度探针，不计入能力题。它们维持所选思考档和输出预算；快检依然受整体采集时限约束。没有这个选项时只复用原测试数据。

斜率分析拟合 `接口输入 ≈ 斜率 × 独立输入 + 固定差额`，从而区分固定追加内容与随长度放大的差异。只有受控长度、足够跨度和适当独立计数证据才提示比例偏高；普通估算只显示描述趋势。固定提示词、不同编码和上游改写仍可能影响结果，不能单凭斜率宣判欺诈。

## 独立的 Token 消耗等级

在本机页面选择“导入我已核实来源的官方同题参考”，或使用原来的 `--reference-report` 与 `--trust-reference`。要匹配型号、题库、种子、具体题目、协议、思考档、预算、重复次数等。两侧须完整答对并有一致且完整的用量、缓存状态证据。缺数据、零用量、失败或截断不评成甲＋。

每个配对任务的原始 Token 比值取等权几何平均 R，避免一项大任务支配总分。读缓存与未读缓存分组显示；这里比较原始 token，不把折扣换算成更少的 token。

| 等级 | 含义 | R（相对官方同题用量） |
|---|---|---|
| 甲＋ | 极少 | 0 < R < 0.2 |
| 甲 | 少很多 | 0.2 ≤ R < 0.6 |
| 乙 | 少一些 | 0.6 ≤ R < 0.9 |
| 丙 | 平均 | 0.9 ≤ R ≤ 1.1 |
| 丁 | 多一些 | 1.1 < R ≤ 2 |
| 戊 | 多很多 | 2 < R < 3 |
| 戊＋ | 极多 | R ≥ 3 |

这是公开的产品分段，不是经过科学标定的欺诈概率。它只描述本套题本次运行的上报消耗；推理长度有随机性，单次大幅差异不足以证明虚报。没有合格参考显示“待对照”，不伪造官方基线。

## 缓存、推理与钱

OpenAI 的缓存读取属于 input_tokens 的一部分；隐藏 reasoning 已经属于 output_tokens，不能再加一次。Claude 总输入是普通输入 + 缓存写入 + 缓存读取，字段缺失不擅自当零。价格、分组倍率、缓存折扣和实际金额单独查看。New API quota 未取得站点单位定义时不擅自换算美元。

## 隐私与边界

本机服务只监听 127.0.0.1，并采用每次随机路径。原始账单、截图、OCR 文字及登录凭据不写入结果；本地结果保留匹配后的数值。公开分享继续使用 `--public-out`，它移除回答、账单逐行记录、请求 ID 等隐私内容。请勿将个人 reports 目录直接上传。

本机网络测试验证实现正确性，不代表任何真实中转通过验真。自动后台适配当前为 New API；任意网站的交互登录、缺失账单接口、隐藏上游内容和全部 OCR 布局不在通用自动保证范围内。

## 依据

- [OpenAI token counting](https://developers.openai.com/api/docs/guides/token-counting)
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Claude token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [New API routes](https://github.com/QuantumNous/new-api/blob/main/router/api-router.go)
- [New API log controller](https://github.com/QuantumNous/new-api/blob/main/controller/log.go)
