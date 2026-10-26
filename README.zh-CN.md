# RelayLens（中转透镜）

独立运行的 GPT / Claude 中转站检测器。用随机任务、工具调用、同题多次测试、回答分布和延迟，检查中转站是否存在能力下降或不稳定路由。仅使用 Python 标准库，Python 3.10+ 即可，无需安装依赖。

**0.5.1**：在完整 14 类题库、前后端工程语义题和多型号参考对照上，增加可选数字序列行为指纹。复核 lm.ikale.io 与相关论文后，采用整次请求配对的分布检验，单独展示行为差异。程序不会凭一个分数猜测底层型号，也不附带未经实际采集的官方基线。

## 双击使用

Windows 双击 `start.cmd`，按向导填写地址、目标型号、请求模型 ID、API 类型和隐藏输入的 Key。结束后自动打开 HTML 报告，JSON 保存在 `reports/`。

目标列表按 2026-10-26 官方文档核对：GPT-6 Astra、GPT-6.1 Sol、GPT-6 Luna，以及 Claude Fable 5.1、Opus 5.5、Sonnet 5.5、Haiku 5.5。已有旧型号继续保留；也可填写以 `gpt-` 或 `claude-` 开头的目标 ID。实际中转别名放在 `--model`，所选原始型号放在 `--target-model`。

## 命令行使用

无需 pip 安装，直接运行；省略 Key 后会隐藏询问，也支持环境变量 `RELAYLENS_API_KEY`、`RELAY_API_KEY` 和 `T8_API_KEY`。

```powershell
python run_relaylens.py --interactive
python run_relaylens.py --list-targets
python run_relaylens.py --base-url https://gateway.example/v1 --model gateway-alias --target-model gpt-6-astra --task-rounds 5 --repeats 3 --stream --max-output-tokens 4096 --out reports/relay.json --html-out reports/relay.html
```

API 类型：`--api responses`（默认）、`--api chat`（Chat Completions）、`--api messages`（Claude 原生接口，使用 x-api-key 认证）。Claude 中转如果只支持 OpenAI 格式，请选择相应的 chat 或 responses，而非根据名称推断协议。

`--task-effort high` 控制实际任务档位，`omit` 可省略该字段。`--efforts high max` 单独配置参数探针；默认选择文档支持档位。参数拒绝会留证，不能单凭一个不支持的参数判冒充。旧入口 `--logic-rounds` 和 `--quick` 仍兼容。

## 检测内容

- `--pack standard` 保留原有 8 类随机任务：排序逻辑、算术、表达式修复、精确指令、路径算法、调度优化、上下文查找、状态追踪。
- `--pack challenge` 在此基础上增加 6 类：多约束最优值与方案计数、精确条件概率、多表关联汇总、带版本的上下文检索、前端异步状态、后端事务。向导默认选完整题库，仍可选择标准版。
- 前端题覆盖旧请求晚到、清空状态、选择项失效；后端题覆盖幂等重放、失败缓存、版本冲突、资金守恒。答案由本地程序确定。这是工程逻辑检测，不是完整网页生成或浏览器渲染评分。
- `--context-records 1024` 控制完整题库的上下文记录数，最低 32。记录数、输入字符数和 API 返回的 token 用量是不同指标，不能直接当成模型上下文长度认证。
- `--repeats 3`：同一套题重复并打乱顺序，记录同题通过/失败切换，帮助观察混用或不稳定；波动也可能由随机采样、缓存、限额引起。
- 工具闭环：随机工具名及不可预知收据，精确校验参数和返回 JSON 的全部字段与类型；不再靠关键词碰巧出现判通过。
- 延迟：按任务类别分别统计总耗时、P95、MAD、首个文本 token 时间，不把网络排队当成模型身份证据。
- 回答方式：记录每类回答长度、JSON/Markdown 比例；可选 `--fingerprint-samples 20` 对 5 种短回答探针各采样 20 次，与参考做 JSD 和置换检验。该选项额外增加 100 次请求；小样本只报告证据不足。
- 数字序列：可选 `--numeric-samples 30`，额外发送 30 次请求，比较数值偏好、末位数字和位置分布。至少 30 对完整有效回答才做统计检验；3 次仅用于检查接口。每条回答整体作为一个样本，不把数组内的数字冒充独立请求。

内置任务是可复现的基础套件，不是经过标定的“智商表”。**没有可信目标参考时，不能因得分高就断言达到某个旗舰型号。** 高分也可能说明题目对两个模型都太容易。可通过 `--suite-module private_suite.py` 加载自己保留的更难题库；接口仍为 `suite(seed, rounds)`。

## 官方和中转对照

先用你自己的官方 API Key，在可信官方端点跑同一配置。例如 GPT：

```powershell
python run_relaylens.py --base-url https://api.openai.com/v1 --model gpt-6-astra --target-model gpt-6-astra --seed 20261026 --task-rounds 5 --repeats 3 --stream --max-output-tokens 4096 --out reports/official.json
```

再用中转站自己的 Key 跑候选，增加参考路径。只有你已核实官方报告来源时，添加 `--trust-reference`：

```powershell
python run_relaylens.py --base-url https://gateway.example/v1 --model gateway-alias --target-model gpt-6-astra --seed 20261026 --task-rounds 5 --repeats 3 --stream --max-output-tokens 4096 --reference-report reports/official.json --trust-reference --out reports/candidate.json --html-out reports/candidate.html
```

Claude 官方可用 `https://api.anthropic.com/v1`、`--api messages` 和相应的 `claude-*` 目标。两边应采用相同协议与配置；不同协议的报告会标为不可直接配对。使用同一 seed、题库承诺哈希、目标、档位、输出预算、流式设置、重复数与采样设置，逐题核对 prompt hash。跨版本旧报告不能强行用于新版本认证。

进行复杂能力对照时，给上面**两条命令同时**增加 `--pack challenge --context-records 1024 --timeout 300`，并把两边的 `--max-output-tokens` 同时改为 `32768`。正式比较的题目、参数和输出预算必须一致。向导会显示预计请求次数；这些调用按供应商实际计费。预算不足导致截断时，先解决截断再解释能力分数。

## 使用数字序列辅助核验

给前面官方和中转的**两条采集命令同时**增加 `--numeric-samples 30`，使用相同 seed、协议、思考档、输出预算、流式设置，以及可选的 `--fingerprint-temperature`。数字数组较长，请给两边足够的输出预算；截断或格式无效不会当成模型差异。每侧额外 30 次请求，按端点计费；不会把 Key 或回答交给 lm.ikale.io，也不会自动下载该站的参考库。

HTML 报告中的“数字序列行为指纹”单独展示有效请求数、参考型号和统计结果。显著差异意味着这批回答的行为不一致，系统提示、参数、时间变化也可能造成差异；未检出差异不证明模型相同，也不排除少量混用。**p 值不是“真货率”，本工具不估算掺水百分比。** 行为结果不增加或扣除能力分数。

这个功能借鉴 [lm-detector](https://github.com/Ikaleio/lm-detector) 的数值偏好思路，但使用本地实现和你独立采集的可信官方参考。它不是该网站排名器的移植，也没有继承其准确率。论文、适用前提和暂不采用的方法见 [研究复核](docs/research-review.md)。

同一个官方端点先做两次独立采集，检查其自身波动；再用新的采集批次测中转。比较前固定请求数和判断方法，不要反复尝试直到出现显著结果。若官方自身的行为也经常变化，应先排查条件差异，再解释中转结果。

已经采集的完整本地报告可离线重算；公开脱敏 JSON 不含回答原文，因此不能重新计算行为指纹。能力评分仍可使用结构化结果配对。

## 多型号参考与离线比较

将你实际从官方采集的多个 GPT 或 Claude 型号报告单独放入 `references/` 文件夹。它们必须与候选使用同一题库、seed 和任务配置；不同 API 协议需要各自的参考组。参数探针列表和指纹采样数量可不同，任务对照仍可进行；指纹另外检查采样设置。

```powershell
python run_relaylens.py --compare-report reports/candidate.json --reference-dir references --trust-reference --out reports/compared.json --html-out reports/compared.html
```

这条命令完全离线，不用 Key、不重新计费。也可在在线测试命令中增加 `--reference-dir references`。只有已核实文件夹内**全部**参考来源时才使用 `--trust-reference`；不要把候选本身放进参考目录。来自同一运行的报告不能当自己的参考。参考文件里的自称“可信”标志不会自动生效。

页面逐个显示“能力差距在容差内”“低于参考”“服务失败干扰”“证据不足”或“配置不兼容”。如果多个参考都相符，会保留多个结果，说明这套题还不能把它们分开；不强行猜一个最像的型号。同一型号有冲突的参考运行时，也不会挑最有利的一次。

## 结论

- **D**：没有可用回答，先排查认证、接口、超时和服务状态。
- **C**：本套题表现偏低、服务完成率不足，或相对可信参考存在能力损失；会分别说明原因，不能仅由此锁定替代模型是谁。
- **B**：已获得基础结果，但目标校准、样本量或证据不足。
- **A**：在至少 30 道不同题、可信参考与配对条件下，任务退步比例的单侧精确二项上界不超过容差。默认容差为 10 个百分点，可用 `--loss-margin` 配置；多参考时还会调整比较次数带来的误判风险。

失败、网络错误和截断计入任务总数；重复同一题不会伪装成更多独立题。报告保留配对差距的聚类 bootstrap 区间；“区间包含 0”不会自动给 A。A 只说明本套题与参考接近，任何等级都无法证明内部权重身份、排除按题路由或保证未来不变。

页面同时显示全部任务正确率、请求完成率、完成后的正确率、同题每次均通过比例。参考能力下降结论还要检查双方都完成的题目；网络失败导致的差距单列为服务问题。接近满分时会提示题库可能太容易。前后端题和扩展上下文增加了覆盖面，但区分某两个真实旗舰型号的效果仍需要官方对照实测。

Chat 默认使用新版 `max_completion_tokens`，旧网关可选 `--chat-token-field max_tokens`。官方文档指出 GPT-6 Astra / GPT-6.1 Sol 的 Chat 接口不支持工具调用：探针仍会执行并留证，但不会因此把任务能力判为低端；测试它们的工具能力应使用 Responses。

## 文件和隐私

完整本地 JSON/HTML 保留回答供复核；Key 和认证信息会脱敏。分享用 `--public-out reports/public.json`，该文件还移除错误原文、标准/解析答案、中转别名、出口城市和组织、邮箱、URL、路径与 IP；题目 ID 做哈希。公开测量报告仍可与本地报告对照任务成绩，但由于不含回答文本，不能用于指纹分布对照。自定义题库的类别名、型号名等标签仍应使用不含个人信息的名称。

`--route direct` 绕过环境代理；`--proxy http://proxy.example:8080` 指定 HTTP 代理。可选 `--egress` 查询 ipinfo.io 出口，`--no-egress` 关闭；查询不携带模型 Key。此功能不更改全局网络配置。

社区框架选型与采纳理由见 [research-review.md](docs/research-review.md)。方法、统计边界和资料见 [methodology.md](docs/methodology.md)、[threat-model.md](docs/threat-model.md)、[anti-adaptation.md](docs/anti-adaptation.md)。
