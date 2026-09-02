以下是对 Mini AutoSTAT 技术路线的详尽任务分解。分解遵循既定原则：**架构（LangGraph + langgraph-supervisor Leader-Worker）不动**，所有任务都在该架构内展开；标注了每个任务的产出、验收标准、依赖关系，以及与考核题的映射。

---

## 总览：六个里程碑

| 里程碑 | 内容 | 对应考核要求 |
|--------|------|-------------|
| **M1** | 项目骨架与基础设施 | 可配置性、可复现性 |
| **M2** | 状态管理与全链路记录 | 状态记录、终止机制 |
| **M3** | Worker Agents 与真实工具调用 | 真实工具调用、代码生成执行 |
| **M4** | Leader Agent 与 Supervisor 编排 | 任务规划、结果检查 |
| **M5** | 中断/重规划 + 报告生成 | 题目 B 核心流程闭环 |
| **M6** | 验证、演示与提交材料 | 异常处理、运行记录、README |

依赖关系：M1 → M2 → M3 → M4 → M5 → M6，其中 M3 与 M4 的部分任务可并行。

---

## M1：项目骨架与基础设施

### T1.1 环境与依赖清单
- **产出**：`requirements.txt`（langgraph、langgraph-supervisor、langchain-openai、pandas、statsmodels、matplotlib 等最小集）、`.env.example`、`.gitignore`（排除密钥与产物）
- **细节决策**（助手自行决定，事后报告）：依赖版本取当前稳定版，不锁死 patch 版本
- **验收**：`pip install -r requirements.txt` 一次成功

### T1.2 目录结构落定
- **产出**：在待确认目录草案（P-004）基础上创建空骨架：`agents/`、`core/`、`workflows/`、`knowledge/`、`examples/`、`logs/`、`outputs/`
- **依赖**：P-004 待你确认

### T1.3 LLM 客户端封装
- **产出**：`core/llm.py` —— 基于 `ChatOpenAI`，读取 `base_url`/`api_key`/`model` 环境变量，默认指向 **GLM-5.3-Flash**（OpenCode Go）；单例获取函数；JSON 输出解析辅助
- **映射**：可配置性（模型名称、API 通过环境变量/配置设置）
- **验收**：一段脚本调用 LLM 返回文本成功

### T1.4 配置系统
- **产出**：`core/config.py` —— 支持配置文件 + 命令行参数：`max_turns`（默认如 15）、`data_path`、`output_dir`、`log_path`、`model` 覆盖
- **映射**：可配置性、终止机制（预算参数）
- **验收**：`python app.py --max-turns 10 --data examples/xxx.csv` 可解析

---

## M2：状态管理与全链路记录

### T2.1 AnalysisState 定义
- **产出**：`core/state.py` —— 按根 README 设计实现 `AnalysisState`（TypedDict）：`messages`（add_messages reducer）、`current_hypothesis`、`data_path`、`data_cleaned`、`completed_steps`、`planned_steps`、`statistical_results`、`visualizations`、`interrupted`、`current_iteration` 等
- **性质**：架构核心件，字段清单我会先列出请你过目
- **验收**：图编译时可被 StateGraph 接受

### T2.2 Checkpointer 接入
- **产出**：`workflows/graph.py` 中 `compile(checkpointer=MemorySaver())`，按 thread_id 会话隔离；**注释中写明 PostgresSaver 升级路径**（D-003）
- **验收**：同一 thread_id 两次 invoke 状态延续

### T2.3 全链路执行记录（考核重点）
- **产出**：`core/tracer.py` —— 一个轻量记录器，每次节点执行后追加一条记录：`{时间戳, 节点/Worker 名, 输入摘要, 决策, 工具调用及参数, 输出/错误, 下一步动作}`；写入 `logs/run_<ts>.jsonl` + 终端同步打印
- **映射**：状态记录（完整过程可追溯）、运行记录材料
- **性质**：实现细节由助手决定，事后报告
- **验收**：跑一次分析后 jsonl 能还原每一步

### T2.4 终止机制
- **产出**：在 Leader 逻辑中实现三重终止：① 所有步骤完成且合格 → `FINISH` + 报告；② `max_turns` 硬上限（来自配置）→ 强制收敛出总结；③ 用户明确停止
- **映射**：终止机制（避免无限循环）
- **验收**：构造一个不收敛场景验证 max_turns 生效

---

## M3：Worker Agents 与真实工具调用

### T3.1 数据工具（data_tools）
- **产出**：`core/tools/data_tools.py` —— `load_csv(path)`、`check_variable_types(df)`、`check_missing_values(df)`、`detect_outliers(df)`、`describe_data(df)`；返回结构化 dict
- **映射**：题目 B 第 1 条（检查变量类型、缺失值与异常）
- **验收**：对示例 CSV 输出正确的类型/缺失/异常报告

### T3.2 统计工具（stat_tools）
- **产出**：`core/tools/stat_tools.py` —— `run_descriptive_stats`、`run_correlation_test`（Pearson/Spearman 自动选择+正态性检查）、`run_granger_causality`（含平稳性前置检验 ADF）、`run_regression_analysis`（OLS + 残差诊断）；每个工具返回：统计量、p 值、效应量、**假设条件是否满足**、适用性警告
- **映射**：题目 B 第 2、4 条（方法及适用条件；检查模型假设、结果异常）
- **验收**：相关+格兰杰+回归三个工具在示例数据上跑通并报告假设检查

### T3.3 可视化工具（viz_tools）
- **产出**：`core/tools/viz_tools.py` —— `create_chart(df, plot_type, ...)` 生成 PNG 到 `outputs/figures/`，**同时生成等价文本表格**（图表类型、坐标轴、数据范围、相关系数、分组摘要、前 N 数据点）
- **映射**：README 多模态兼容特性；题目 B 第 3 条（保存关键结果和图表）
- **验收**：散点图 + 折线图各一张，文本表格信息完整可读

### T3.4 受限代码执行工具（code_tools）
- **产出**：`core/tools/code_tools.py` —— `execute_python(code)` 在受控子进程中执行 LLM 生成的分析代码（超时限制、禁止危险操作的白名单式检查、捕获 stdout/stderr/异常）；失败时返回结构化错误信息供修复循环使用
- **性质**：**安全边界设计**属于需要你过目的点（方案：子进程 + 超时 + 简单静态黑名单；不追求沙箱级安全，demo 够用）
- **映射**：题目 B 第 3 条（自动生成并执行代码）、统一要求 2（真实工具调用）
- **验收**：执行一段正确代码返回结果；执行一段有 bug 的代码返回清晰错误

### T3.5 Worker Agent 构建（3 个，P-001 待确认）
- **产出**：`agents/workers/` 下三个 `create_react_agent`：
  1. `data_preprocessor`（数据预处理：绑定 T3.1 工具，负责数据质量检查与清洗建议）
  2. `statistical_analyst`（统计分析：绑定 T3.2 + T3.4，可生成代码→执行→按报错自修复，最多 N 轮修复）
  3. `visualizer`（可视化：绑定 T3.3）
- 每个 Worker 有明确的系统提示词（职责、输出 JSON 格式、工作原则）
- **依赖**：T3.1–T3.4
- **映射**：题目 B 第 4 条（必要时修改方案并重新执行）
- **验收**：单独 invoke 每个 Worker，给定任务能正确调工具并返回结构化结果

---

## M4：Leader Agent 与 Supervisor 编排

### T4.1 Leader 系统提示词与决策逻辑
- **产出**：`agents/leader.py` —— `create_supervisor(model, agents, prompt)`；提示词覆盖：意图识别（新假设/继续/中断/修改参数）、任务规划（拆步骤）、质量控制（检查 Worker 输出合格性）、终止条件、FINISH 输出格式
- **映射**：任务规划、结果检查（独立的检查反思环节）
- **验收**：给定用户假设，Leader 能产出合理的步骤序列并正确调度 Worker

### T4.2 主图组装
- **产出**：`workflows/graph.py` —— supervisor 图 + 入口节点（意图/规划）+ 出口节点（报告生成）；接入 tracer（T2.3）与 checkpointer（T2.2）
- **依赖**：T3.5、T4.1
- **验收**：端到端跑通「假设 → 预处理 → 统计 → 可视化 → FINISH」

### T4.3 质量控制与重试
- **产出**：Leader 对 Worker 结果的检查规则（结果为空、p 值缺失、假设不满足 → 打回重做或换方法，最多重试 2 次）
- **映射**：结果检查、异常处理
- **验收**：注入一次坏结果，Leader 能识别并重新调度

---

## M5：中断/重规划 + 报告生成

### T5.1 用户中断机制
- **产出**：CLI 中支持用户在任意时刻输入新指令（新假设/修改方向/停止）；通过 `interrupt` 机制挂起当前流程，Leader 读取 `completed_steps` 后重新规划
- **映射**：README「可中断与可重规划」核心特性
- **验收**：演示中途中断 → 注入新假设 → 流程基于已完成工作继续

### T5.2 结构化报告生成
- **产出**：`agents/reporter.py`（或 Leader 直接生成）—— 汇总 state 中全部结果，输出 Markdown 报告，**必须包含六要素：数据说明、方法及选择原因、结果、不确定性（置信区间/效应量）、限制、不应得出的结论**；保存到 `outputs/report.md`
- **映射**：题目 B 第 5 条
- **验收**：报告六要素齐全且内容与实际运行结果一致（非编造）

### T5.3 RAG 预留接口（D-004）
- **产出**：`knowledge/retriever.py` —— `retrieve(query, k) -> list[str]` 抽象接口 + 一个返回空列表/静态方法目录的占位实现；Leader/Worker 提示词组装处预留注入点
- **验收**：替换为真实现时无需改动工作流代码

---

## M6：验证、演示与提交材料

### T6.1 示例数据准备（P-003 待确认）
- **产出**：`examples/renewable_energy_gdp.csv` —— 若干国家/年份的可再生能源占比/发电量 + GDP（来源 OWID 等公开数据，注明出处与许可）
- **依赖**：P-003 待你确认

### T6.2 异常恢复演示（考核硬性要求）
- **产出**：**至少一次真实失败及恢复**的完整记录。计划两种途径选其一或都用：① 首轮生成的统计代码因数据非平稳导致格兰杰检验报错 → Agent 检测后先做差分再重跑；② 代码执行报错 → 修复循环成功
- **映射**：异常处理
- **验收**：运行日志中可见「失败 → 检测 → 恢复 → 成功」完整链

### T6.3 完整运行日志
- **产出**：一次完整演示会话的 `logs/run_*.jsonl` 与终端记录，展示每步决策、工具调用和结果
- **映射**：运行记录材料

### T6.4 端到端联调与考核项自检
- **产出**：对照 `Test_Agent.md` 题目 B 8 条 + 统一要求 8 条的逐项自检表；修复发现的缺口
- **验收**：16 项全部有对应实现与证据

### T6.5 README 更新与技术报告素材
- **产出**：README 补齐「环境→安装→一条命令运行」完整说明、目录结构说明、已知限制；技术报告素材（架构图、设计取舍、失败案例）从决策记录与运行日志中提炼
- **映射**：可复现性、提交材料