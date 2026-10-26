# RelayLens（中转透镜）

独立运行的 GPT / Claude 中转站检测器。用随机任务、工具调用、同题多次测试、回答分布和延迟，检查中转站是否存在能力下降或不稳定路由。仅使用 Python 标准库，Python 3.10+ 即可，无需安装依赖。

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

- 8 类随机任务：唯一解排序逻辑、多步算术、代码修复及边界检查、严格指令、最短路径与路径计数、组合优化、长上下文查找、事务状态追踪。答案在本地求解，不发给被测模型。
- `--repeats 3`：同一套题重复并打乱顺序，记录同题通过/失败切换，帮助观察混用或不稳定；波动也可能由随机采样、缓存、限额引起。
- 工具闭环：随机工具名、真实类型调用、校验参数，再回传结果并检查回答使用所有结果字段。
- 延迟：按任务类别分别统计总耗时、P95、MAD、首个文本 token 时间，不把网络排队当成模型身份证据。
- 回答方式：记录每类回答长度、JSON/Markdown 比例；可选 `--fingerprint-samples 20` 对 5 种短回答探针各采样 20 次，与参考做 JSD 和置换检验。该选项额外增加 100 次请求；小样本只报告证据不足。

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

## 结论

- **D**：没有可用回答，先排查认证、接口、超时和服务状态。
- **C**：基础题表现偏低，或相对可信参考存在超过容差的能力损失；不能仅由此锁定替代模型是谁。
- **B**：已获得基础结果，但目标校准、样本量或证据不足。
- **A**：在至少 30 道不同题、可信参考与配对条件下，任务退步比例的一侧 95% 上界不超过容差。默认容差为 10 个百分点，可用 `--loss-margin` 配置。

失败、网络错误和截断计入任务总数；重复同一题不会伪装成更多独立题。报告保留配对差距的聚类 bootstrap 区间；“区间包含 0”不会自动给 A。A 只说明本套题与参考接近，任何等级都无法证明内部权重身份、排除按题路由或保证未来不变。

## 文件和隐私

完整本地 JSON/HTML 保留回答供复核；Key 和认证信息会脱敏。分享用 `--public-out reports/public.json`，该文件移除回答文本、完整 URL、路径和 IP；内存中的工具上下文不受脱敏影响。

`--route direct` 绕过环境代理；`--proxy http://proxy.example:8080` 指定 HTTP 代理。可选 `--egress` 查询 ipinfo.io 出口，`--no-egress` 关闭；查询不携带模型 Key。此功能不更改全局网络配置。

方法、统计边界和资料见 [methodology.md](docs/methodology.md)、[threat-model.md](docs/threat-model.md)、[anti-adaptation.md](docs/anti-adaptation.md)。
