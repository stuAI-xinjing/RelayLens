# RelayLens（中转透镜）

RelayLens 是一个不依赖第三方运行库的黑盒审计工具，用来比较 OpenAI 兼容网关的**协议兼容性、工具调用和临时任务表现**。它不能证明网关私下使用了哪一个模型权重。

## 最简单的运行方式

需要 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
relaylens --base-url https://gateway.example/v1 --model example-model
```

如果要核验中转站声称的 GPT 或 Claude 型号，请显式选择目标型号：

```powershell
relaylens --base-url https://gateway.example/v1 --model gpt-6-astra --target-model gpt-6-astra
```

支持 GPT-6 Astra、GPT-6.1 Sol、GPT-6 Luna、GPT-5.6 Sol，以及 Claude
Opus 5、Sonnet 5、Opus 4.8、Opus 4.6、Sonnet 4.6、Haiku 4.5。报告会把
`model_requested`（实际发给网关的型号）与 `target_model`（网关声称的型号）分开保存。

程序会隐藏读取 API Key。也可以先设置：

```powershell
$env:RELAYLENS_API_KEY = "你的临时测试 Key"
```

建议使用测试专用或限额 Key，不要把 Key 写在命令行、截图、Issue 或报告中。

## 运行参数

- `--api responses`：Responses API
- `--api chat`：Chat Completions API
- `--route direct`：绕过系统代理
- `--proxy http://proxy.example:8080`：指定 HTTP 代理
- `--seed 20261005`：固定随机题，便于官方和中转 A/B 对照
- `--task-rounds 10`：增加每类随机题数量；请求次数和费用也会增加
- `--public-out report-public.json`：输出去除密钥、完整 URL、本机路径、IP 和原始 Prompt 的公开报告
- `--reference-report official.json`：与相同套件、种子和 API 风格的参考报告做配对比较
- `--suite-module C:/private/private_suite.py`：加载本地私有题库模块，模块需提供 `suite(seed, rounds)`

## 结果如何理解

- **D**：接口不可用、未认证或目标模型没有列出。
- **C**：至少一个独立能力层明显不一致，例如工具闭环失败、参数大量拒绝或临时题表现异常。
- **B**：接口和任务表现正常，但没有足够的可信参考端点。
- **A**：在同一套随机题和配对比较中与参考端点接近。A 只表示行为相似，不证明后端权重相同。

## 防止中转站针对题目适配

不要把“加密题目”当成主要防护。中转站必须收到解密后的明文才能回答，所以它仍可能看到、记录和识别题目。加密只能保护本地文件存储，不能让接收请求的端点看不见内容。

更可靠的做法是：

1. 把公开题库当作可复现的基础套件。
2. 把高价值题库放在本地私有文件或私有仓库。
3. 通过 `--suite-module` 临时加载私有题库。
4. 常规检测使用随机种子；只有官方与中转 A/B 对照时才固定种子。
5. 使用每次变化的工具名、题目顺序和数值。
6. 只公开脱敏报告和题库承诺哈希，不公开原始题目。

题库承诺哈希可以证明两次 A/B 测试用了同一个本地文件，但不能隐藏发送给中转站的明文题目。详细方法见 [`docs/methodology.md`](docs/methodology.md)、[`docs/threat-model.md`](docs/threat-model.md) 和 [`docs/anti-adaptation.md`](docs/anti-adaptation.md)。
