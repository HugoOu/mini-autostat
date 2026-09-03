# 考核项自检表（T6.4）

对照 [Test_Agent.md](Test_Agent.md) 题目 B 8 条 + 统一功能要求 8 条，逐项给出实现位置与运行证据。

> 证据中引用的运行记录均在 `logs/` 下；`run_20260903_130750_fa21ed` 为 M6 完整演示会话
> （80 事件，终端记录 `outputs/m6_demo_terminal.txt`，含真实异常恢复链），
> `run_20260903_092821_4de83b` 为 M5 验收会话。

## 一、题目 B（Mini AutoSTAT）8 条

| # | 考核要求 | 实现位置 | 运行证据 | 状态 |
|---|---------|---------|---------|------|
| B1 | 读取自然语言分析问题和数据文件，检查变量类型、缺失值与异常 | `app.py`（假设输入）+ `agents/workers/data_preprocessor.py` + `core/tools/data_tools.py`（`check_variable_types` / `check_missing_values` / `detect_outliers`） | 各次运行日志 data_preprocessor 步骤输出类型/缺失/IQR 异常报告（如 run_…092821 第 4、12 行） | ✅ |
| B2 | 提出分析计划，说明拟采用的方法及其适用条件 | `agents/leader.py`（规划提示词）+ `core/tools/stat_tools.py`（每工具返回"假设条件是否满足"与适用性警告）+ `knowledge/retriever.py` 静态方法目录（`--retriever static` 注入） | 日志 leader 规划与 transfer 调度链；报告「方法及选择原因」章节 | ✅ |
| B3 | 自动生成并执行 Python 分析代码，保存关键结果和图表 | `core/tools/code_tools.py`（`execute_python`：子进程+超时+静态黑名单）+ `core/tools/viz_tools.py`（PNG→`outputs/figures/`，附等价文本表格） | 日志 tool_call 含 execute_python 参数与 stdout；M4 会话产出 4 张 PNG（run 记录 visualizations: 4） | ✅ |
| B4 | 检查模型假设、运行错误或结果异常；必要时修改方案并重新执行 | 三层：① `stat_tools` 假设前置检查（如格兰杰 ADF 平稳性）；② Leader 即时打回（`rejection_counts` 上限 2）；③ sync 节点确定性 JSON 校验回环（T4.3） | M6 演示 run_…130750：工具报错→`execute_python` 派生变量重跑（事件 48-53）、非平稳→差分→重跑（事件 54-57）、图表列不存在→修正（事件 62-74）；run_…092821 记录 QC 打回与补做 | ✅ |
| B5 | 输出结构化报告（数据说明、方法、结果、不确定性、限制、不应得出的结论） | `agents/reporter.py`（素材收集→LLM 成文→`validate_report` 校验→兜底降级） | `outputs/report.md`（兜底版）与 `outputs/report_llm.md`（LLM 版）六要素齐全、数值与日志一致 | ✅ |
| B6 | 说明为什么选择当前方法、何时可能不可靠 | 报告「方法及选择原因」「限制」「不应得出的结论」章节 + stat_tools 的 `assumptions`/`warnings` 字段 | report_llm.md：伪回归风险、未检验不称显著等 | ✅ |
| B7 | （题目说明）系统接收自然语言任务，自动完成多步规划与工具调用 | `app.py` → `workflows/graph.py` 主图（init→team→sync→gate→checkpoint→report） | 任一 run 日志可完整还原 | ✅ |
| B8 | （题目说明）最小可运行、可复现、可解释设计取舍 | 一条命令运行（README 快速开始）；36 项离线测试；[Decision_Log.md](Decision_Log.md) 25 条决策记录含根因分析与取舍 | pytest 36 passed；Decision_Log | ✅ |

## 二、统一功能要求 8 条

| # | 考核要求 | 实现位置 | 运行证据 | 状态 |
|---|---------|---------|---------|------|
| U1 | 任务规划：拆分多步执行 | Leader 提示词规划 + `planned_steps`/`completed_steps` 状态字段 | 日志中 Leader 的 transfer_* 调度序列即为执行计划 | ✅ |
| U2 | 真实工具调用（文件读写 + Python 执行） | `core/tools/registry.py` 注册 native 工具；`data_tools` 真实读写 CSV；`code_tools` 真实子进程执行 | 日志每条 tool_call 带真实参数与真实输出（含报错）；D-024 零工具证据打回；M6 演示工具计数 data_preprocessor=15 / descriptive=3 / modeling=6 / visualizer=7（run_…130750） | ✅ |
| U3 | 状态记录：每步输入/决策/工具调用/输出/错误/后续动作 | `core/tracer.py` → `logs/run_<id>.jsonl`（schema 含 ts/actor/action/decision/tool/error/next） | 任一 jsonl 可逐步还原（M5 验收人工检验已核对） | ✅ |
| U4 | 结果检查：独立检查/反思环节 | ① sync 节点确定性校验（JSON 可解析、必需字段、image_path、工具证据 D-024）；② gate QC 回环；③ Leader 提示词质量控制；④ 图表工具证据回写（D-025）；⑤ `validate_report` | run_…092821 日志 sync 反馈消息与打回记录；run_…130750 工具证据计数 | ✅ |
| U5 | 终止机制：明确最大步数/预算/成功/失败退出 | `core/state.py` `check_termination` 三重条件 + `max_turns` 硬上限 + `recursion_limit` 预算（`invoke_budget`）+ 用户 stop/Ctrl+C | M5 验收 `--max-turns 8` 正常收敛；人工检验五以 `--max-turns 2` 验证预算终止 | ✅ |
| U6 | 异常处理：至少一次真实失败及恢复 | ① 建模代码报错→修复循环（`max_repair_rounds`）；② 格兰杰 ADF 非平稳→差分后重跑；③ LLM 超时→重试→报告兜底 | M6 演示 run_…130750 两条完整链：工具报错→`execute_python` 派生变量重跑（事件 48-53）、ADF 非平稳→差分→重跑（事件 54-57）；M4 会话 12 轮含多次真实修复 | ✅ |
| U7 | 可配置性：模型/API/预算/数据路径/参数可配置 | `core/config.py`（.env + CLI，CLI 优先）：`--model --leader-model --worker-model --max-turns --max-repair-rounds --retriever --data --output-dir --log-dir`；D-026 Leader/Worker 分模型 + 思考链 extra_body | M5 验收用 `--max-turns 8`、演示用不同 `--data`，均生效 | ✅ |
| U8 | 可复现性：README 提供安装到运行完整命令，一条主命令启动 | [README.md](README.md)「快速开始」：环境→安装→配置→一条命令；示例数据提取命令可复现 | README + examples/README.md | ✅ |

## 三、提交材料对照

| 材料 | 要求 | 位置 | 状态 |
|------|------|------|------|
| 完整代码 | 源码+配置+依赖+示例数据，不含密钥 | 本仓库；`.env` 已被 .gitignore 排除，`.env.example` 提供模板 | ✅ |
| README | 环境/安装/启动/目录结构/输入输出/已知限制 | [README.md](README.md)（2.0.0，按实际实现重写） | ✅ |
| 技术报告 | ≤6 页，架构/流程/设计/结果/失败案例/改进 | 素材索引见 README「提交材料索引」；Decision_Log + 运行日志提供全部素材 | ✅（素材齐备，正式成文按需导出） |
| 运行记录 | ≥1 次完整运行日志 | `logs/run_20260903_130750_fa21ed.jsonl`（80 事件含异常恢复链）+ `outputs/m6_demo_terminal.txt`（终端记录）+ `outputs/report.md`（演示产出报告）；三者已随仓库提交至 `artifacts/m6_demo/`（logs/outputs 运行目录不入 Git） | ✅ |

## 四、诚实声明

- 使用生成式 AI 辅助编码（Trae IDE + GLM/Kimi 模型）：架构设计、决策与验收由负责人主导，代码由 AI 依任务分解实现并经负责人指导验收，全部决策记录见 [Decision_Log.md](Decision_Log.md)。
- 未复制任何开源项目代码；langgraph-supervisor 为公开依赖库，按其公开 API 使用。
- 所有运行日志为真实运行产生，未伪造。
