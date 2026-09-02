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