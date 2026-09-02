# Mini AutoSTAT 未来升级方向（Roadmap）

> 本文档记录 demo 阶段之后的技术演进方向。所有方向均**不改变现有架构**
> （LangGraph + langgraph-supervisor 的 Leader-Worker 架构、工具注册表、
> 预留接口），只向已预留的接口中填充实现。
> 优先级评估标准：对考核点（方法泛化、异常处理、结果检查）的增益 ÷ 实现代价。

---

## U-1 df 回写通道（带 Leader 审核）

- **问题**：`execute_python` 子进程内对数据集的修改（如差分列）不会回写
  进程内 DataStore，生成代码与注册工具无法组合使用（D-015 第 9 条）。
- **方案**：约定生成代码可将结果保存为 `df_output.csv`；`execute_python`
  检测到该文件后**不直接写回**，而是把回写请求（含新列描述、行数、来源
  代码片段）提交给 **Leader Agent 审核**——负责人已确认此约束：
  Leader 校验通过（列名合法、无覆盖关键列、来源代码无危险操作）才写入
  DataStore，并在 tracer 中记录 `check` 事件；驳回则附原因返回 Worker。
- **状态**：设计定稿，M5/M6 视联调需要实现。

## U-2 RAG 统计方法目录（D-004 预留接口的直接填充）

- **问题**：内置统计工具是写死的确定性实现；遇到目录之外的方法，Worker
  只能依赖模型内部知识写代码，存在 API 幻觉风险（目前靠修复循环兜底）。
- **方案**：建立方法目录 `knowledge/methods_catalog.jsonl`，条目结构：
  `{方法名, 解决的问题, 适用条件, 违反后果, 代码模板, 参考文献}`；
  Worker 生成代码前按任务描述调用 `knowledge/retriever.py` 的
  `retrieve(query, k)` 取 top-k 条目注入提示词。
- **接口现状**：`retrieve(query, k) -> list[str]` 已预留（T5.3），
  替换实现时工作流零改动。
- **状态**：接口已预留，目录内容待建。

## U-3 方法评议 Agent（统计审稿人）

- **问题**：Leader 兼任质量检查，难以深度验证统计方法的适配性。
- **方案**：增加独立 Worker，输入"方法-数据性质-结论"三元组，输出
  通过/驳回意见；对应考核题 B 的"独立的检查、反思或验证环节"。
- **状态**：方向明确，未排期。

## U-4 工具合成沉淀（技能库）

- **方案**：某段生成代码经检验成功且被复用 N 次后，由 Leader 提议、
  人工确认后固化为注册表新工具（`provider="synthesized"`）。
  系统随使用积累能力，注册表是现成的沉淀位置。
- **状态**：未排期。

## U-5 MCP 动态接入

- **方案**：注册表 `provider` 字段已预留（D-008）。未来接入专业统计
  MCP server 时，在 `core/tools/__init__.py` 注册处替换为 adapter 包装
  并标注 `provider="mcp"`，所有 Worker 的工具发现逻辑零改动。
- **状态**：适配点已就位，未排期。

## U-6 Checkpointer 升级 PostgresSaver（D-003 既定终态）

- **方案**：`pip install langgraph-checkpoint-postgres`；
  `compile(checkpointer=PostgresSaver.from_conn_string(...))` +
  一次性 `setup()` 建表。状态定义、工作流逻辑零改动。
- **状态**：demo 冻结后执行。

---

## 演进原则（沿承合作原则第 1 条）

1. 任何升级不得改变 Leader-Worker 架构与技术路线，需负责人批准后实施；
2. 优先填充已预留接口（retrieve / registry provider / checkpointer），
   避免侵入式改造；
3. 每项升级落地时在 Decision_Log 新增 D 条目并在本文件标注状态。
