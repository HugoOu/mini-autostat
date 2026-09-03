# Mini AutoSTAT

一个基于 **LangGraph + langgraph-supervisor** 的 Leader–Worker 多智能体自动化统计分析系统：接收一条自然语言分析假设与一份 CSV 数据，由 Leader Agent 规划调度四个专职 Worker Agent（数据预处理 / 描述统计 / 统计建模 / 可视化），自动完成数据分析全流程，收敛后产出一份**问题驱动的叙事式分析报告**（含图表与等价文本表格）。

系统**数据无关**：`--data` 可指向任意 CSV 数据集，仓库自带的 OWID 能源数据仅为演示示例（见 [examples/README.md](examples/README.md)）。

---

## 功能特性

- **Leader–Worker 编排**：Leader（规划/质检/收敛判断）+ 4 个专职 Worker，工具调用与交接消息全量留痕；
- **实时 CLI 进度**：stream 模式逐事件转译为 `[调度] / [完成] / [质检] / [收敛] / [报告]` 一行式进度；
- **两类人工暂停点**：中断点（可终止/注入新指令）与确认点（可追加任务续跑），支持 Ctrl+C 安全收敛；
- **终止机制**：Leader 判定收敛 + `max_turns` 硬上限 + 用户主动终止，三重保险防无限循环；
- **结果防编造**：报告只能引用确定性序列化的运行素材；六章节缺失自动校验重试，LLM 全部失败时退回确定性兜底报告；
- **异常自恢复**：代码报错自修复重试、统计假设不满足时自动差分/换方法、渲染失败自动修正；
- **模型分层可配置**：Leader / Worker / 报告生成三层模型与思考链独立配置；
- **状态持久化**：SQLite checkpointer，会话可从检查点恢复（含报告重生成）。

## 系统架构

```
用户假设 + CSV
     │
     ▼
init（注入运行事实） → team（Leader 调度 ⇄ 4 个 Worker） → sync（确定性质检）
     ▲                        │                                 │
     │      不合格/未覆盖打回  │                                 ▼
     └──────────── gate（回环判断）◄──────────────────── 汇总归档
                                      │ Leader FINISH
                                      ▼
                          checkpoint（确认点 interrupt）
                                      │ 用户确认
                                      ▼
                          report（LLM 成文 + 校验 + 兜底） → outputs/report.md
```

| 角色 | 职责 | 内置工具 |
|------|------|----------|
| Leader | 任务分解、调度、质检反馈、收敛判断 | transfer_to_* 交接工具 |
| data_preprocessor | 数据体检：加载/类型/缺失/异常/筛选 | load_csv 等 5 个数据工具 |
| descriptive_analyst | 描述统计与分布刻画 | run_describe 等 |
| modeling_analyst | 相关/回归/格兰杰/平稳性，含生成代码执行 | 统计工具 + execute_python |
| visualizer | 图表渲染（PNG + 等价文本表格，英文图表） | create_chart |

所有工具经 `core/tools/registry.py` 注册（`native` provider，预留 MCP 接入点）；知识检索经 `knowledge/retriever.py` 工厂（`null`/`static`，预留 RAG 接口）。

## 环境要求

| 项 | 要求 |
|----|------|
| 操作系统 | Windows / macOS / Linux（示例命令以 PowerShell 为准） |
| Python | ≥ 3.11（开发环境 3.11.2） |
| LLM | 任意 OpenAI-compatible API（默认 OpenCode Go；亦兼容 Moonshot、DeepSeek 官方等） |
| 网络 | 能访问 LLM API 端点 |

## 安装

```powershell
# 1. 创建虚拟环境
python -m venv .venv

# 2. 安装依赖
.\.venv\Scripts\pip.exe install -r requirements.txt

# 3. 配置密钥：复制模板为 .env 并填入真实 API Key（切勿提交 .env）
Copy-Item .env.example .env
#   编辑 .env，至少填写 OPENAI_API_KEY
```

## 快速开始（一条主命令）

```powershell
.\.venv\Scripts\python.exe app.py
```

不带参数启动即为完整分析会话：默认加载 `examples/owid-energy-data.csv`，回车使用内置示例假设（中国 2000-2023 可再生能源与 GDP 关系），随后自动执行到收敛并生成报告。

指定自有数据与假设（推荐）：

```powershell
.\.venv\Scripts\python.exe app.py --data examples/renewable_energy_gdp.csv --hypothesis "对比中美两国 2000-2023 年可再生能源占比与 GDP 的描述统计"
```

**会话内交互**：

| 场景 | 操作 |
|------|------|
| 确认点（Leader 每轮 FINISH 后） | 回车 / `stop` = 生成报告结束；输入文本 = 追加任务续跑 |
| 中断点（质检回环/追加任务轮） | 回车 = 继续；`stop` = 终止并收敛报告；输入文本 = 注入新指令 |
| 运行中任何时候 | Ctrl+C = 标记终止并安全收敛到报告 |

## 配置

优先级：命令行参数 > `.env` 环境变量 > 内置默认值。

**命令行参数**（`python app.py --help`）：

| 参数 | 说明 | 默认 |
|------|------|------|
| `--data` | CSV 数据文件路径 | `examples/owid-energy-data.csv` |
| `--hypothesis` | 分析假设（缺省进入交互输入） | 内置示例 |
| `--model` | 通用/回退 LLM 模型名 | `OPENAI_MODEL` 或 `glm-5.3-flash` |
| `--leader-model` / `--worker-model` / `--report-model` | 分角色专属模型 | 依次回退上层 |
| `--max-turns` | Leader 调度步数硬上限 | `12` |
| `--max-repair-rounds` | 代码报错自修复最大轮数 | `3` |
| `--retriever` | 知识检索 provider：`null` / `static` | `null` |
| `--output-dir` / `--log-dir` | 输出/日志目录 | `outputs` / `logs` |

**环境变量**（`.env`，完整模板见 [.env.example](.env.example)）：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | **必填**，LLM API 密钥 |
| `OPENAI_BASE_URL` | OpenAI-compatible 端点 |
| `OPENAI_MODEL` | 通用模型 |
| `OPENAI_LEADER_MODEL` / `OPENAI_WORKER_MODEL` / `OPENAI_REPORT_MODEL` | Leader（规划质量优先）/ Worker（吞吐优先）/ 报告生成（长文质量）专属模型 |
| `OPENAI_LEADER_EXTRA_BODY` / `OPENAI_WORKER_EXTRA_BODY` / `OPENAI_REPORT_EXTRA_BODY` | 随请求体透传的 JSON 附加字段（如思考链开关、`reasoning_effort`） |
| `MAX_TURNS` / `MAX_REPAIR_ROUNDS` | 运行预算 |
| `DATA_PATH` | 数据文件路径 |
| `OPENAI_TEMPERATURE` | 强制覆盖所有调用的 temperature（部分模型仅允许特定值） |

## 输入与输出格式

**输入**

- **分析假设**：自然语言字符串（`--hypothesis` 或启动后交互输入）；
- **数据**：任意 CSV 文件。首次使用建议至少包含假设中提到的列；系统会先做数据体检（类型/缺失/异常值），按假设筛选工作集。示例数据见 [examples/README.md](examples/README.md)。

**输出**（均在运行结束时打印路径）

| 文件 | 格式 | 说明 |
|------|------|------|
| `outputs/report.md` | Markdown | 问题驱动叙事报告：问题与数据 → 分析过程 → 主要发现 → 可靠性 → 局限与适用边界 → 结论（含「不应得出的结论」小节）；图表以 `![](figures/xxx.png)` 相对路径嵌入 |
| `outputs/figures/*.png` | PNG | 每张图对应一条等价文本表格（随状态归档），图表文字全英文 |
| `logs/run_<id>.jsonl` | JSONL | 全链路事件：`ts / step / actor / action / decision / tool / input_summary / output_summary / error / next`，含每次工具调用的真实参数与输出 |
| `checkpoints.sqlite` | SQLite | LangGraph 检查点，支持中断恢复与报告重生成 |

## 目录结构

```
mini_autostat/
├── app.py                        # CLI 入口：stream 实时进度 + 两类暂停点
├── core/
│   ├── config.py                 # 配置（CLI > env > 默认）
│   ├── llm.py                    # ChatOpenAI 封装（分角色模型/思考链）
│   ├── state.py                  # AnalysisState（共享状态）+ 终止机制
│   ├── tracer.py                 # JSONL 运行记录器
│   └── tools/
│       ├── registry.py           # 工具注册表（native provider，预留 MCP）
│       ├── data_tools.py         # 加载/类型/缺失/异常/筛选
│       ├── stat_tools.py         # 描述统计/相关/格兰杰/回归（OLS+诊断）
│       ├── viz_tools.py          # create_chart（PNG + 等价文本表格）
│       └── code_tools.py         # execute_python（子进程+超时+静态黑名单）
├── agents/
│   ├── leader.py                 # Leader（RAG/Pandas 助手，规划与质检）
│   ├── reporter.py               # 报告生成（素材序列化 + LLM 成文 + 校验 + 兜底）
│   └── workers/                  # 4 个专职 Worker（create_react_agent）
├── workflows/
│   └── graph.py                  # 主图组装 init→team→sync→gate→checkpoint→report
├── knowledge/
│   └── retriever.py              # 检索工厂（null/static，预留 RAG）
├── examples/
│   ├── README.md                 # 示例数据来源、许可与提取命令
│   ├── renewable_energy_gdp.csv  # 中美 2000-2023 演示子集（48 行）
│   └── owid-energy-data.csv      # 完整 OWID 能源数据集（23,377 行 × 130 列）
├── tests/                        # pytest 离线冒烟测试（M1–M6，42 项）
├── scripts/                      # 诊断与运维脚本（报告探针/断点恢复/重生成等）
├── logs/                         # 运行日志（自动生成，不入库）
├── outputs/                      # 报告与图表（自动生成，不入库）
├── requirements.txt
├── .env.example                  # 环境变量模板（复制为 .env 使用）
└── FUTURE_UPGRADES.md            # 升级方向清单
```

## 测试

```powershell
# 离线回归（42 项，不调用 LLM）
.\.venv\Scripts\python.exe -m pytest tests -q
```

端到端在线验收可用小数据集快速验证：

```powershell
.\.venv\Scripts\python.exe app.py --data examples/renewable_energy_gdp.csv --max-turns 6 --hypothesis "对比中美两国 2000-2023 年可再生能源占比与 GDP 的描述统计"
```

## 已知限制

1. **中断粒度为「轮之间」**：单个 Worker 执行中不可暂停；Ctrl+C 在 super-step 边界收敛，不保留“半成品”现场。
2. **单工作数据集**：工具维护全局 `current` 数据集，多数据集对比时后者覆盖前者（可从 `raw` 重建）。
3. **RAG 为占位实现**：`static` provider 是关键词匹配的内置方法目录，非向量检索；真实 RAG 按 [FUTURE_UPGRADES.md](FUTURE_UPGRADES.md) U-2 升级，工作流零改动。
4. **代码执行安全边界为 demo 级**：子进程 + 超时 + 静态黑名单，非沙箱级隔离，不应处理不可信输入。
5. **报告内容受素材约束**：报告只引用真实运行结果，素材未记录的项写“（运行中未记录）”；LLM 不可用时退回确定性兜底报告（显式标注）。
6. **提供方稳定性**：GLM 系列对报告级长调用偶发 HTTP 500，已通过报告专属模型分层重试缓解（报告生成默认 Qwen3.8-Flash）。

## 升级方向

见 [FUTURE_UPGRADES.md](FUTURE_UPGRADES.md)：报告撰写 Worker 化、df 回写 Leader 审核、RAG 统计方法目录、方法评议 Agent、工具合成沉淀、MCP 动态接入、PostgresSaver 等七项，均不改变现有架构。

## 许可证

MIT License。示例数据来自 [Our World in Data](https://github.com/owid/energy-data)（CC BY 4.0），见 [examples/README.md](examples/README.md)。

---

**文档版本**: 3.0.0（重写为通用标准格式）
**最后更新**: 2026-09-03
