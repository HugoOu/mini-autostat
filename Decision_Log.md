# Mini AutoSTAT 项目决策记录（Decision Log）

> 本文档逐条记录项目开发过程中的每一项询问与决策，作为架构演进的唯一权威记录。
> 每条决策包含：背景、备选方案、最终决策、决策理由、影响范围。

---

## 〇、合作原则（由项目负责人制定，最高约束，所有决策不得违背）

1. 项目负责人把握整个技术架构和技术路线，助手不得自行调整；确需调整时，必须先询问负责人意见；
2. 对于非架构变动的、较为简单的、较为安全的技术细节，助手可自行决定，但变动之后必须向负责人报告。

## 补充约束（第二轮对话由负责人确认）

3. demo 阶段不引入 RAG，但必须预留检索接口；
4. demo 使用 OpenCode Go 提供的 GLM-5.3-Flash 模型；
5. Checkpointer 使用 MemorySaver 替代 PostgresSaver（PostgresSaver 仍为终态选型，仅后置）；
6. 目录结构可适当调整，不必完全遵循根 README 规划；
7. **严禁拷贝、抄袭、剪切任何开源项目或参考项目（含 AutoSTAT v2）源码**，所有代码从零原创编写，仅允许概念与设计思想层面的借鉴；
8. 项目必须完整满足 `Test_Agent.md` 题目 B（Mini AutoSTAT）的全部要求及统一功能要求。

---

## 决策记录

### D-001 | 2026-09-02 | 整体架构与技术路线
- **背景**：项目启动，确立基本技术路线。
- **备选方案**：固定顺序流水线（AutoSTAT v2 模式）/ LangGraph 单 Agent 循环 / LangGraph + langgraph-supervisor Leader-Worker 多智能体。
- **决策**：采用 **LangGraph + langgraph-supervisor 的 Leader-Worker 多智能体架构**。
- **决策人**：项目负责人（写入根 README，不可调整）。
- **影响范围**：全部代码组织方式、状态管理、考核项映射。

### D-002 | 2026-09-02 | LLM 提供方选型
- **背景**：Agent 需要一个 OpenAI-compatible 的 LLM API。
- **备选方案**：OpenAI GPT-4o / DeepSeek / OpenCode Go 提供的 GLM-5.3-Flash。
- **决策**：使用 **OpenCode Go 提供的 GLM-5.3-Flash**，通过 OpenAI-compatible 接口接入（`ChatOpenAI` + 自定义 `base_url`）。
- **决策人**：项目负责人。
- **影响范围**：`core/llm` 配置、`.env` 模板、README 部署说明。

### D-003 | 2026-09-02 | Checkpointer 选型
- **背景**：LangGraph 支持多级 checkpointer，README 原方案为 PostgresSaver。
- **备选方案**：PostgresSaver / SqliteSaver / MemorySaver。
- **决策**：demo 阶段使用 **MemorySaver**，预留一行代码切换到 PostgresSaver 的升级路径；理由：三者实现同一 `BaseCheckpointSaver` 接口，demo 场景下中断/恢复均发生在单次进程生命周期内，MemorySaver 完全满足且零部署成本。
- **决策人**：助手提议，项目负责人批准（附原理讲解）。
- **影响范围**：`app.py` 编译处一行代码；不触碰架构。

### D-004 | 2026-09-02 | RAG 知识库策略
- **背景**：README 原方案包含 FAISS + sentence-transformers 的 RAG 知识库。
- **备选方案**：完整 RAG / 关键词匹配 / 不引入 RAG。
- **决策**：demo 阶段**不引入 RAG**，但 **预留检索接口**（定义统一的 `retrieve(query, k) -> list` 抽象与注入点），后续可在不改动工作流的前提下替换为向量检索实现。
- **决策人**：助手提议，项目负责人批准。
- **影响范围**：`knowledge/` 模块设计为接口占位实现。

### D-005 | 2026-09-02 | 代码复用边界
- **背景**：工作区包含 AutoSTAT v2 完整源码，需明确可否复用。
- **备选方案**：直接拷贝裁剪 / 仅参考设计思想。
- **决策**：**不允许拷贝、抄袭、剪切任何源码**；AutoSTAT v2 仅作为架构设计理念参考（分阶段工作流、代码生成+修复循环、方法目录等思想），所有代码从零原创；技术报告中将明确声明 AI 辅助范围与参考来源。
- **决策人**：项目负责人。
- **影响范围**：全部代码原创性要求；技术报告与贡献声明写法。

### D-006 | 2026-09-02 | 目录结构
- **背景**：根 README 规划了一套目录结构。
- **备选方案**：严格按 README / 按项目实际情况适当调整。
- **决策**：**可以适当调整**，以清晰满足考核要求为准；调整后须在 README 与决策记录中同步说明。
- **决策人**：项目负责人。

### D-007 | 2026-09-02 | Worker 分工细化
- **背景**：原方案 3~4 个 Worker（预处理/统计分析/可视化，代码执行并入统计分析）。
- **决策**：细化为 **4 个 Worker**：
  1. 数据预处理 Worker（类型/缺失/异常检查、国家年份筛选、列裁剪）；
  2. 描述性统计分析 Worker（均值/方差/分布/趋势/分组对比，固定工具实现，产出图表需求单）；
  3. 建模分析 Worker（相关/格兰杰/回归等，含代码生成→执行→报错自修复循环，产出图表需求单）；
  4. 可视化 Worker（共享下游，接收两个分析 Worker 的图表需求单，统一渲染 PNG + 等价文本表格，文本表格写回共享状态供解读）。
- **决策人**：项目负责人。
- **影响范围**：agents/workers/ 结构、任务分解 T3.5、图表需求单数据结构设计。

### D-008 | 2026-09-02 | 工具实现形态（Skill/MCP vs 原生 @tool）｜待负责人最终确认
- **背景**：负责人询问为何不采用 Skill（如 claude-statistical-analysis-skill）或 MCP Server（如 pandas-mcp-server）形式实现 Worker 工具。
- **助手论证要点**：
  1. Skill 属 Claude 生态规范，非 LangGraph 组件，引入即绑定生态；
  2. 考核要求「不提交自己无法解释的主要代码」，第三方 MCP server 内部为黑盒，可解释性差；
  3. 考核要求一条主命令启动，MCP 需额外安装/启动/管理 server 进程，失败模式成倍增加；
  4. MCP 基于 JSON 文本传输，DataFrame 需跨进程序列化，丢失类型且低效；
  5. MCP 调用需在适配层额外埋点才能满足全链路追溯。
- **建议决策**：demo 用**原生 @tool**；通过 `core/tools/registry.py` 工具注册表**预留 MCP 适配点**（未来替换为 MCP server 只改注册表，Worker/Leader 零改动），与根 README「MCP Tool 集成」预留接口规划一致。
- **状态**：✅ 负责人已确认（"全部同意"，2026-09-02）。

### D-009 | 2026-09-02 | 最终目录结构（P-004）
- **背景**：M1 骨架搭建需确定目录结构，负责人授权助手提出草案执行。
- **决策**：
  ```text
  mini_autostat/
  ├── app.py                  # CLI 主入口（后续里程碑实现）
  ├── requirements.txt        # 依赖清单
  ├── .env.example            # 环境变量模板（不含真实密钥）
  ├── .gitignore
  ├── owid-energy-data.csv    # 示例数据（负责人提供，P-003）
  ├── agents/                 # Leader 与 4 个 Worker（D-007）
  │   └── workers/
  ├── core/                   # config / llm / state / tracer / tools
  │   └── tools/              # registry.py 为 MCP 适配点（D-008）
  ├── workflows/              # 主图组装（graph.py，M4）
  ├── knowledge/              # RAG 预留接口（D-004，M5）
  ├── outputs/                # figures/ + reports/（运行产物，不入库）
  ├── logs/                   # 全链路运行记录 jsonl（不入库）
  └── tests/                  # 测试
  ```
- **决策人**：助手提出，负责人授权执行。

### D-010 | 2026-09-02 | M1 技术细节登记（助手自行决定，依原则 2 向负责人报告）
1. `.gitignore` 排除 `AutoSTAT/`（参考项目不纳入本项目 Git 提交，规避考核抄袭风险，呼应 D-005）；
2. `python-dotenv` 为可选导入：缺失时退回系统环境变量，不阻塞程序启动；
3. 运行预算参数（`MAX_TURNS` / `MAX_REPAIR_ROUNDS` / `DATA_PATH`）同时支持环境变量与命令行参数，**命令行优先**，满足考核可配置性要求；
4. `core/llm.py` 附带 `parse_json_block` 容错解析函数（容忍 ```json 围栏与前后缀文本），供后续 Worker 结构化输出统一使用；
5. `core/config.py` 支持 `python -m core.config` 自检输出（脱敏显示 api_key），作为 M1 验收手段之一。

### D-011 | 2026-09-02 | M1 环境细节登记（助手自行决定，依原则 2 向负责人报告）
1. **虚拟环境**：系统默认 Python 为 3.14，部分科学计算包兼容性有风险，故用 `py -3.11` 创建 `.venv`（Python 3.11.2）；
2. **运行时环境变量**：后续所有 Python 运行加 `PYTHONDONTWRITEBYTECODE=1`，规避沙箱对基础安装目录 pycache 写入的限制；
3. **依赖版本事实**：实际安装版本为 langgraph 1.2.11 / langgraph-supervisor 0.0.31 / langchain 1.3.18 / langchain-openai 1.6.0 / pandas 3.0.5，均为当前镜像源最新稳定版（requirements.txt 只锁下限）；
4. **冒烟测试**：新增 `tests/test_m1_smoke.py`（配置覆盖、JSON 解析、注册表、LLM 客户端构造 4 项），后续里程碑沿用此模式累积测试。

### D-012 | 2026-09-02 | LLM 环境配置完成（M2 前置）
- **背景**：负责人提供 OpenCode Go 的 endpoint 与 API key。
- **决策**：写入项目根目录 `.env`（已被 .gitignore 排除，不入库）；`OPENAI_BASE_URL=https://opencode.ai/zen/go/v1`，`OPENAI_MODEL=glm-5.3-flash`；`.env.example` 同步更新为真实 endpoint（key 保持占位符）。
- **验证**：`scripts/check_llm.py` 真实调用 GLM-5.3-Flash 成功返回（connectivity-ok）。
- **安全声明**：API key 只存在于本地 `.env`，不进入任何提交物；技术报告与日志中一律脱敏。

### D-013 | 2026-09-02 | tracer 事件 schema 与截断策略（助手自行决定，向负责人报告）
1. 运行记录为 `logs/run_<run_id>.jsonl`，逐行一个 JSON 事件，schema v1 字段：`schema/ts/step/actor/action/input_summary/decision/tool/output_summary/error/next`；
2. `actor` 白名单校验（leader / 四 Worker / reporter / user / system），`tool` 字段强制包含 `name` 与 `provider`（呼应 D-008 注册表）；
3. 摘要字段超过 600 字符自动截断并标注 `[truncated N chars]`，防止工具大输出撑爆日志；
4. 每条事件即刻 `flush` 落盘，进程异常退出不丢已记录步骤（利于考核"失败与恢复过程"的取证）；
5. `run_id` 格式 `日期_时间_短uuid`，方便按运行检索。

### D-014 | 2026-09-02 | M2 状态设计登记（助手自行决定，向负责人报告）
1. `AnalysisState` 采用 `TypedDict(total=False)`：所有字段可缺省、节点可只返回变更字段，由 LangGraph 合并；
2. 字段分组：对话历史 / 用户假设 / 数据状态 / 分析进度 / 结果存储 / 流程控制，共 17 个字段（含 D-007 图表需求单 `chart_requests` 与终止字段 `iteration`/`stop_reason`）；
3. 终止检查 `check_termination` 为纯函数（state + max_turns → (bool, reason)），三重条件优先级：显式 stop_reason > 用户中断 > max_turns 硬上限；
4. `record_step` 为纯函数追加器，不原地修改状态，便于节点返回值风格统一。

### D-015 | 2026-09-02 | M3 工具层与 Worker 层技术细节（助手自行决定，向负责人报告）
1. **进程内数据缓存**：新增 `core/datastore.py`，工具通过命名 key 共享 DataFrame（`current` 为工作数据集），这是 Worker 间数据协作通道，避免重复读盘；
2. **工具返回约定**：所有工具返回 JSON 字符串；错误以 `{"error": "..."}` 结构返回而非抛异常，Agent 可读错误并调整方案（呼应考核异常处理）；
3. **格兰杰结构化拒绝**：`run_granger_causality` 前置 ADF，非平稳时不执行、返回 `ok=false` + 差分建议——天然构成"失败→检测→恢复"链；
4. **相关分析自动选法**：Shapiro-Wilk（n>5000 改用偏度峰度近似）双方均正态 → Pearson，否则 Spearman 并附警告；
5. **代码执行安全边界**（P-006 方案）：静态黑名单（os/sys/subprocess/shutil/socket/ctypes/eval/exec/open/getattr/globals）→ 隔离子进程（`python -I -B`，-I 忽略环境变量故加 -B 防写 .pyc）→ 超时强杀（默认 60s）→ stdout 截断 4000 字符 → 生成代码保存的 PNG 回收到 outputs/figures；工作数据集先落盘 df_input.csv 注入变量 df；
6. **pandas 3.0 适配**：字符串列是新 `str` dtype，类型判断改用 `is_string_dtype`（踩坑记录）；
7. **statsmodels 新版适配**：`adfuller` 显式 `result_object=False` 消 FutureWarning；`grangercausalitytests` 已无 `verbose` 参数；
8. **图表输出**：Agg 后端、dpi=150、中文字体 Microsoft YaHei、文件名 slug + 时间戳防覆盖；
9. **已知限制（重要）**：`execute_python` 子进程内对 df 的修改**不会**回写到进程内 DataStore——M3 在线验收中 modeling_analyst 自行绕过（在同一脚本内完成差分+检验），M4 联调时视需要增加 df 回写通道；
10. **在线验收**：`scripts/check_workers.py` 用真实 GLM-5.3-Flash 逐个 invoke 4 个 Worker 全部通过；modeling_analyst 自主完成"Spearman 自动切换 → 格兰杰被拒 → 一阶差分仍非平稳 → 二阶差分 + KPSS 交叉验证 → 检验结论"全链。

### D-016 | 2026-09-02 | IDE 缓冲区覆盖磁盘文件事件（风险登记）
- **现象**：stat_tools.py 与 viz_tools.py 的已保存编辑被 IDE 中打开的旧缓冲区覆盖回旧内容（viz_tools.py 一度成为"新旧混合体"），导致测试反复失败；
- **处置**：整文件重写统一版本后恢复一致；
- **约定**：助手修改文件后，负责人若在 IDE 中打开了同一文件，请勿用旧缓冲区保存覆盖；建议修改后 IDE 端执行"重新加载/还原文件"。

### D-017 | 2026-09-02 | df 回写审核约束 + 升级方向文档（负责人指示）
1. **df 回写必须经 Leader Agent 审核**（负责人明确指示）：未来实现 U-1 回写通道时，生成代码产出的数据集变更不直接写入 DataStore，须经 Leader 校验（列名合法性、关键列保护、来源代码安全性）通过后方可写入，并在 tracer 留痕；
2. 新建 [FUTURE_UPGRADES.md](FUTURE_UPGRADES.md) 记录六项升级方向（U-1 df 回写带审核 / U-2 RAG 方法目录 / U-3 方法评议 Agent / U-4 工具合成 / U-5 MCP 动态接入 / U-6 PostgresSaver），演进原则：不动架构、优先填充已预留接口、落地须负责人批准。

### D-018 | 2026-09-02 | M4 编排技术细节（助手自行决定，向负责人报告）
1. **外层控制图 + supervisor 子图**：`create_supervisor` 返回未编译 StateGraph（源码确认：START→supervisor，supervisor→4 Worker 条件边，Worker→supervisor），以 `state_schema=AnalysisState` 编译为子图节点 `team`；外层图增加 init（入口）/ sync（结果同步与校验）/ gate（终止与回环决策）/ report（出口）四个控制节点——supervisor 架构不变，控制节点在外围；
2. **状态字段扩展**（state.py 新增 3 字段）：`rejection_counts`（各 Worker 被打回次数，上限 2）、`outer_loops`（外层回环计数，上限 3，防 supervisor 过早 FINISH 后死循环）、`synced_msg_count`（消息游标，增量解析 Worker 输出）；
3. **max_turns 的兑现方式**：iteration 定义为已完成 Worker 调度数（len(completed_steps)），gate 节点每轮检查 `check_termination`；同时外层 invoke 传 `recursion_limit=max_turns*8+30` 作为 langgraph 层面的硬预算兜底（supervisor/Worker 内部循环会消耗步数，无法精确映射到"轮"，故取宽松倍数，只防失控不干预正常流程）；
4. **T4.3 双层质量控制**：① supervisor 循环内由 Leader 提示词驱动（看到 Worker 输出立即判断合格性，不合格当场打回，最多 2 次）；② sync 节点做确定性校验（JSON 可解析、必需字段存在、可视化有 image_path），不合格注入校验反馈消息，gate 据此回环让 Leader 处理；
5. **Worker 输出解析**：按 JSON 块的关键字段分类归属（data_overview→预处理 / findings→描述统计 / analyses→建模 / charts→可视化），不依赖 message.name（各 provider 对 name 字段行为不一）；
6. **report 节点 M4 为最小实现**（确定性汇总 state 写 outputs/report.md），M5 替换为 LLM 六要素报告。

### D-019 | 2026-09-02 | LLM 客户端超时与重试（助手自行决定，向负责人报告）
- **背景**：诊断过程中出现网络层 TLS 握手中断（`EOF occurred in violation of protocol`），Agent 可能因网络劣化无限挂起；
- **决定**：`core/llm.py get_llm()` 统一设置 `timeout=120s` + `max_retries=2`（可用 kwargs 覆盖），单点封装、所有 Agent 生效；
- **补录（2026-09-03）**：M5 在线验收期间提供方延迟两次超过 3 次尝试的 361s 上限（reporter 调用持续超时约 600s），`max_retries` 2→4（最长约 600s/次调用），架构与调用方式零改动；离线回归 31 项全部通过。

### D-020 | 2026-09-02 | 主图 Checkpointer 选型与子图死锁根因修正
- **现象**：外层控制图嵌套 supervisor 子图后，`MemorySaver` 与 `SqliteSaver` 两种 checkpointer 下 invoke 均在进入 team 子图时挂起（tracer 日志均止步于 init 的 route 事件）；无 checkpointer 的同一图 77s 正常跑通，team 子图单独 invoke 108s 正常；
- **根因**：LangGraph 子图默认**继承父图 checkpointer**，嵌套 checkpoint 写入引发死锁（对照实验五组隔离确认）；
- **修正**：`create_supervisor(...).compile(checkpointer=False)` 显式关闭子图继承，持久化只保留外层图级别——子图消息经 `add_messages` 已汇入主状态，外层 checkpoint 足以支撑 M5 中断恢复；
- **选型**：demo 采用 `SqliteSaver`（文件级持久化，可跨进程续跑，比 MemorySaver 更贴近 M5 需求）；升级 PostgresSaver 仅改 `build_app` 的 compile 处（D-003 终态不变）；
- **教训**：此前初判"MemorySaver 与子图嵌套组合死锁、SqliteSaver 可解"不准确——真正的变量是子图是否继承 checkpointer，与 saver 实现无关。

### D-021 | 2026-09-03 | M5 中断/报告/检索预留实现细节（助手自行决定，向负责人报告）
1. **T5.3 RAG 预留接口**：`knowledge/retriever.py` 定义 `BaseRetriever.retrieve(query, k) -> list[str]` 抽象接口 + 工厂 `create_retriever(provider)`；两个占位实现：`NullRetriever`（恒空，默认）、`StaticMethodCatalog`（内置方法适用条件知识条目，关键词匹配，与 stat_tools 的方法选择逻辑对齐）；config 新增 `retriever` 项（`--retriever` / 环境变量 `RETRIEVER`）；**唯一注入点**在 init 节点——按用户假设检索，命中则以 SystemMessage 注入对话（注入格式由 `build_context_block` 统一）。未来换真实 RAG：新增子类 + 工厂注册 + 改配置，工作流零改动（T5.3 验收）；
2. **T5.2 六要素报告**：`agents/reporter.py` 三层结构——① `collect_materials` 确定性序列化 state（报告只能引用实际运行结果，防编造）；② LLM 按六要素成文 + `validate_report` 确定性校验章节齐全性，缺项携带反馈重试 1 次；③ LLM 异常或两次缺项时 `_fallback_report` 确定性兜底（六要素齐全、标注兜底来源），报告生成永不因 LLM 故障中断；
3. **T5.1 中断机制**：`build_app` 新增 `interrupt_before` 参数——编译期 `interrupt_before=["team"]`，每轮团队执行前静态暂停（配合 SqliteSaver resume）；CLI 入口 `app.py` 交互协议：回车=继续 / `stop`=终止 / 其他文本=注入新指令（HumanMessage，Leader 基于 completed_steps 重规划）；终止路径用 `update_state(as_node="sync")` 写入 `stop_reason` 使下一步直达 gate→report，**跳过当前轮 team** 避免重跑；Ctrl+C 落点为最近 super-step 边界，走同一终止路径。**已知限制**：同一 team 轮次内部不可中断（粒度=轮之间），demo 够用；
4. **D-016 复发记录**：本轮 config.py（`--retriever` 参数行、AppConfig.retriever 字段）与 workflows/graph.py（reporter/retriever 导入行）先后被 IDE 旧缓冲区覆盖，均由测试失败定位后补回。提示：请在 IDE 中对这些文件执行"还原文件"或关闭标签页。

### D-022 | 2026-09-03 | 用户确认点：静态中断改为 FINISH 后动态中断（助手自行决定，向负责人报告）
- **背景**：M5 在线验收发现，静态 `interrupt_before=["team"]` 仅在 team 执行前暂停，首轮正常分析全程无暂停点，用户无法在 Leader 完成计划后选择「出报告 or 追加任务」——交互粒度不符合 T5.1 意图；
- **修正**：主图新增 `checkpoint` 节点（gate 之后、report 之前）：Leader FINISH 后经 gate 路由至 checkpoint，通过**动态 `interrupt()`** 询问用户；`build_app` 新增 `user_checkpoint` 参数（默认 False=直通，保持离线测试与 M4 兼容）。图结构：`gate ─┬→ team（QC 回环）├→ checkpoint ─┬→ team（追加任务）├→ report └→ END`；
- **状态**：`AnalysisState` 新增 `user_directive` 字段（None=出报告；文本=注入新指令，同时清空 `stop_reason` 并以 HumanMessage 回注 team，Leader 基于已完成工作重规划）；
- **app.py 交互协议升级为两类暂停点**：①中断点（team 执行前，静态）：回车=继续 / stop=终止 / 文本=注入指令；②确认点（Leader FINISH 后，动态）：回车/stop=生成报告 / 文本=追加任务。恢复均用 `Command(resume=...)`，持久化依赖外层 SqliteSaver，**不触碰子图嵌套**（D-020 死锁教训）；
- **在线验收**（run 20260903_092821）：确认点 1（已完成 2 步）追加「美国同期对比」任务 → 续跑完成美国预处理+描述统计 → 确认点 2 确认出报告 → 收敛。LLM 报告因提供方持续超时按 D-021 设计降级为确定性兜底（六要素齐全），中断机制本身验证通过。

### D-023 | 2026-09-03 | 开发期 LLM 提供方切换 OpenCode → Moonshot Kimi（负责人指示，助手执行）
- **背景**：M5 在线验收期间 OpenCode 链路（opencode.ai，Cloudflare 边缘）间歇性网络黑洞——TCP 可建立但 TLS/HTTP 不完成，请求未达网关（后台无调用记录），120s×5 次重试全部超时；探测显示恢复后 8s 即正常返回，证实与模型推理速度无关，纯属链路故障；
- **决定**（负责人提供 Key）：`.env` 切换为 Moonshot OpenAI-compatible 接口（`https://api.moonshot.cn/v1`，`kimi-k2.6`），OpenCode 配置注释保留备切回；`core/llm.py get_llm()` 新增 `OPENAI_TEMPERATURE` 环境变量覆盖点——`kimi-k2.6` 仅允许 temperature=1，设该变量强制覆盖所有调用方，无厂商特判逻辑，切回 GLM 后删除即恢复 0.0 确定性；
- **权衡**：temperature=1 使输出确定性下降（demo 阶段可接受）；架构零改动（D-002 OpenAI-compatible 设计的预期收益）；
- **验证**：Moonshot 探测 4.6s 返回；用检查点中的真实 M5 状态单独调用 `generate_report`，108s 产出 LLM 六要素报告（校验零缺项），统计量与 tracer 日志逐项一致、无编造——T5.2 LLM 报告路径在线补验通过；离线回归 31 项通过。

### D-024 | 2026-09-03 | 工具调用证据强制检查：从"提示词约束"升级为"确定性校验"（M6 演示发现的真实缺陷修复）
- **背景**：M6 演示运行（run 20260903_120814，kimi-k2.7-code-highspeed）复盘检查点消息发现：**全部 4 个 Worker 都没有调用任何真实工具**（消息流中只有 transfer_* 交接，无 load_csv/run_descriptive_stats/create_chart 等调用），但输出了看似精确的统计结果——模型凭参数记忆编造。追溯 M5 运行（GLM）同样存在此问题（此前"报告数值与日志一致"的核对只证明了一致性，未证明真实性）；M4 会话产出过 4 张真实 PNG，说明工具使用与否随模型/温度漂移，提示词约束不可靠。考核 U2 明确"只在对话中模拟已经运行不算完成"，此为硬性缺陷；
- **修复三层**：
  1. **sync 确定性证据检查**：增量解析时维护 `current_worker` 归属游标（transfer_to_* 置位 / transfer_back 复位）与 `tool_usage` 计数（非交接 tool_call 计数，含失败尝试）；Worker 最终 JSON 若零工具证据 → 判不合格打回，反馈"必须调用工具获取数据后再作答"。新增 `AnalysisState.tool_usage` 字段跨轮累计；
  2. **Worker 工具级日志**（补 T2.3/U3 缺口）：Worker 的 tool_call（含参数）与 tool_result（含错误）逐条写入 tracer，actor 归属到具体 Worker——此前 jsonl 只有 transfer 与最终 JSON，无法满足"运行记录能看到每步工具调用"；
  3. **visualizer 渲染失败不得带病通过**：charts 条目缺 image_path → 判不合格打回（此前渲染失败仅因 JSON 结构完整就判"合格"，导致 Leader 带缺失图表 FINISH）；
- **配套**：data_preprocessor 增加 execute_python 工具（职责内的特征工程，如派生 gdp_growth/差分列——M6 演示中正是因 preprocessor 无法派生列导致恢复链断裂）；四个 Worker 提示词增加"硬性要求"段落说明确定性检查的存在；
- **权衡**：零工具证据一律打回可能误伤"纯解读类"输出——本系统 Worker 职责均为数据操作型，全部需要工具，规则成立；工具调用失败的尝试也计入 usage（有真实尝试即非编造，错误信息由 tool_result 日志留痕）；
- **验证**：新增 3 项离线测试（零工具证据打回 / 渲染失败打回 / 工具日志归属），34 项全部通过；重跑 M6 演示验证真实恢复链（见 D-025 后续记录）。

### D-025 | 2026-09-03 | M6 演示验收通过 + 图表证据确定性回写（助手自行决定，向负责人报告）
- **背景**：D-024 修复后的 M6 完整在线演示（run 20260903_130750_fa21ed，kimi-k2.7-code-highspeed，80 事件，约 6 分钟）通过人工检验。复盘发现两处事实：
  1. **真实恢复链成立**（考核 U6/B4 证据）：① modeling_analyst 先后调用 `run_correlation_test`/`run_regression_analysis` 因分析列不存在报错（事件 48-51）→ 检测后改用 `execute_python` 自行派生 `renewable_share`/`gdp_growth` 并重跑成功（事件 52-53）；② `renewable_share` ADF 水平值 p=0.9968 非平稳 → 一阶差分后 p=0.0233 平稳，格兰杰检验按差分序列执行（事件 54-57）——即"统计代码报错→检测→修复→重跑成功"与"非平稳→差分→重跑"两条链均有完整日志；③ visualizer 亦有"列不存在→修正列名→成功"链（事件 62-74）；工具调用计数 data_preprocessor=15 / descriptive=3 / modeling=6 / visualizer=7；
  2. **新缺口**：visualizer 最终消息缺少 charts JSON 块，sync 无从归档——4 张 PNG 实际渲染成功但 `visualizations` 归档为 0，报告只能写"运行中未记录具体图片文件路径"。零工具证据检查（D-024）管住"没干活"，但没管住"干了活没交结构化结果"；
- **修复**：sync 增加图表证据确定性回写——成功的 `create_chart` 工具结果自带 `image_path` 与等价文本表格，属确定性证据，无论最终 JSON 是否完整都据此回写 `visualizations`（按 image_path 去重，JSON 条目优先，工具结果补缺口），并写 tracer check 事件留痕；
- **权衡**：选择"从工具证据回写"而非"无 JSON 一律打回"——图表已真实渲染，打回只会浪费轮次重渲染同样的图；证据以工具结果为准与 D-024 的立场一致；
- **验证**：新增 2 项离线测试（工具证据回写 / JSON 与工具证据去重），36 项全部通过。

### D-026 | 2026-09-03 | Leader / Worker 分模型（负责人指示，助手执行）
- **背景**：负责人为优化数据分析流程速度，决定 Leader 与 Worker 使用不同 LLM：回到 OpenCode Go 提供方，Leader 用 `glm-5.3-flash`（保持思考链开启，重规划质量优先），Worker 用 `deepseek-v4-flash`（不开启思考链，重执行吞吐）。
- **决策**：
  - `core/config.py` 新增 `leader_model` / `worker_model` 与 `leader_extra_body` / `worker_extra_body`（env：`OPENAI_LEADER_MODEL` / `OPENAI_WORKER_MODEL` / `OPENAI_LEADER_EXTRA_BODY` / `OPENAI_WORKER_EXTRA_BODY`，CLI：`--leader-model` / `--worker-model`，均优先于 env；未配置角色时回退通用 `model`，向后兼容）；
  - `core/llm.py get_llm` 新增 `role` 参数（"leader"/"worker"/None），模型与 extra_body 按角色选取；extra_body 为 JSON 透传字段，思考链开关（GLM 系 `{"thinking": {"type": ...}}`）经 env 配置而非硬编码，规避提供方协议差异；
  - 调用点归属：Leader supervisor = leader 角色；4 个 Worker = worker 角色；**reporter 使用 leader 角色**（助手自决：单次调用、质量优先，对速度无影响）；
  - 本地 `.env` 已切换至 OpenCode Go 并按上述配置生效。
- **验证**：离线测试 +1（角色模型/extra_body 选择与回退、非法 JSON 快速失败），37 项全部通过；在线冒烟确认 glm-5.3-flash（thinking enabled）与 deepseek-v4-flash（thinking disabled）均经 OpenCode Go 网关正常应答。
- **影响范围**：`core/config.py`、`core/llm.py`、`agents/workers/__init__.py`、`agents/reporter.py`、`workflows/graph.py`、README、Self_Check；架构零改动（get_llm 单点封装原则保持）。

### D-027 | 2026-09-03 | 调度完整性检查 + Worker 工具边界裁剪 + 绘图禁令（负责人确认后实施）
- **背景**：负责人 14:28 的验证运行（run_20260903_142858_81360a）暴露三层问题：① Leader（kimi temp=1）在完整分析假设下只调度了 data_preprocessor 就 FINISH，报告既无统计结果也无图表；② data_preprocessor 越权——用 execute_python 做完整分析并用 matplotlib 直接生成 6 张 PNG，绕过 visualizer；③ 绕过 create_chart 的图无等价文本表格、不进 visualizations 状态，报告无法引用（防编造机制如实降级为"运行中未记录"）。
- **决策**（三项确定性修复，不依赖模型自觉）：
  1. **调度完整性检查**：gate 在自然 FINISH 分支（预算耗尽/用户停止不触发）调用 `coverage_feedback`——有图表需求单但 visualizer 无合格步骤，或没有任何分析 Worker（descriptive/modeling）完成 → 打回 Leader 继续调度；每会话最多 1 次（`coverage_challenges` 字段），二次 FINISH 放行避免死循环；
  2. **工具边界裁剪**：data_preprocessor 移除 execute_python（负责人确认前提：不得影响其预处理职能——类型/缺失/异常/筛选均有原生工具覆盖，派生新列由 modeling_analyst 的代码执行完成）；
  3. **绘图禁令**：execute_python 静态黑名单加入 matplotlib/pyplot/savefig/seaborn/plotly，命中拒绝并提示"图表请由 visualizer 通过 create_chart 生成"；执行环境头部不再注入 matplotlib，产物中 figures 字段随之移除。
- **备选方案**：Leader 提示词强化（靠模型自觉，不可靠，弃）；preprocessor 保留受限 execute_python（负责人指出以不影响预处理职能为前提——原生工具已全覆盖，裁剪更干净）。
- **验证**：新增 4 组离线测试（覆盖检查规则 ×5 断言、绘图禁令 ×4 断言），38 项全部通过。
- **影响范围**：`workflows/graph.py`、`core/state.py`（+1 字段）、`agents/workers/data_preprocessor.py`、`core/tools/code_tools.py`。

---

## 待确认事项

| 编号 | 事项 | 助手建议 | 状态 |
|------|------|----------|------|
| P-001 | Worker 分工 | 已按负责人决定细化为 4 个（D-007） | ✅ 已确认 |
| P-002 | 交互形式（CLI 交互式对话，不做 Web 前端） | CLI | ✅ 已确认 |
| P-003 | 示例数据来源 | 负责人已提供 `owid-energy-data.csv`（OWID 完整能源数据集，约 160 列，预处理阶段需筛选） | ✅ 已确认 |
| P-004 | 具体目录结构草案 | 见 D-009 | ✅ 已确认 |
| P-005 | T2.1 状态字段方案 | 负责人已确认 | ✅ 已确认 |
| P-006 | T3.4 代码执行安全边界（子进程+超时+黑名单） | 负责人已确认 | ✅ 已确认 |
| P-007 | D-008 工具实现形态（原生 @tool + 注册表预留 MCP） | 助手建议如 D-008 | ✅ 已确认 |

---

**文档维护规则**：此后每一次架构层面的询问与决策，均须以新条目（D-007、D-008……）追加至本文档；助手自行决定的技术细节变动，报告时同步登记。