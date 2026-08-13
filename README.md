# 外脑伙伴（最小原型 v2）

一个基于用户画像、具备持续自主优化能力的“探索-生成”型 AI Agent 最小原型。
严格按规格说明书实现四个一级模块，零第三方依赖即可运行。

## 运行

```bash
cd waibao_partner_agent
python3 demo.py    # 全自动演示
python3 chat.py    # 真人在终端交互（记忆持久化到 waibao_data/）
```

`chat.py` 支持命令：`查看画像`、`调整画像`、`查看历史`、`接着做`。

## 模块映射

| 规格模块 | 文件 | 核心类 |
| --- | --- | --- |
| 用户画像系统 | `waibao/profile.py` | `ProfileSystem` |
| 任务-框架生成引擎 | `waibao/task_engine.py` | `InputParser` / `GapAnalyzer` / `QuestionGenerator` / `ConfirmationLoop` / `SolutionGenerator` |
| 记忆与进化系统 | `waibao/memory.py` | `LongTermMemory` / `WorkingMemory` / `EpisodicMemory` / `MemoryEvolutionSystem` |
| 交互与反馈界面 | `waibao/interaction.py` | `ConsoleInterface` |
| 主控编排 | `waibao/agent.py` | `PersonalExplorerAgent` |

## 规格覆盖对照

### 2.x 用户画像
- 四维度 + 价值观红线，字段与初始值对齐 2.1
- 首次对话 ≤5 个封闭式问题初始化（2.2）
- 显式反馈立即更新、隐式信号（停滞/反复修改/跳过案例/快速确认/重复提问）自动调整（2.3）
- 每 5 个任务或每 7 天生成画像变化报告并请求确认（2.3）

### 3.x 任务-框架生成引擎
- 意图解析（explore/generate/organize/decide/custom）（3.1）
- 缺口分析：复用高相似历史任务、画像可推断则不问、每次提问 ≤3 个（3.2）
- 封闭式优先提问，追问耐受度低时合并为 1 个问题（3.3）
- 多轮确认 ≤3 轮，连续 3 次拒绝即停止并声明假设（3.4 / 5.4）
- 方案生成匹配画像：宏观先行、结构化、少举例、分段交付（3.5）

### 4.x 记忆与进化
- 三类记忆：长期（JSON 持久化）、短期（内存）、情景（JSON 快照）（4.1）
- 记忆调用：检索 top-3 相似任务，相似度 > 0.8 判定同类、复用框架并跳过提问；
  同时加载画像快照注入引擎上下文（4.2）
  - 原型阶段用「领域 0.4 + 意图 0.4 + bigram 余弦 0.2」近似语义相似度；
    接入真实 embedding（Chroma/FAISS）时替换 `EpisodicMemory.retrieve_similar` 即可
- 进化算法：显式 `w + lr*(target-w)`、隐式 `w + lr*delta`、
  lr 初始 0.3 随 30 天 ×0.9 衰减、>30 天未更新字段回退 10%、
  单次变化 > 0.3 触发主动确认（4.3）
- 放弃点管理：四阶段切分（需求澄清/框架草案/内容填充/成品交付）、
  每阶段结束暂停询问、放弃点记录、断点续传主动提醒、动力保鲜预览版（4.4）

### 5.x 交互与反馈
- 输出语气/格式随画像；structure_density > 0.7 时成品交付用表格（5.1）
- 每次方案后附带 1-5 分评分行，评分进入记忆与进化（5.2）
- `查看画像` / `调整画像` 命令（5.3）
- 模糊输入先澄清领域与目标；冲突内容（营销 vs 讨厌套话）提醒二选一；
  中途新任务时旧任务标记 abandoned；`查看历史` 列出任务摘要（5.4）

### 6.2 最小原型必须包含
- ✅ 画像初始化对话（5 问以内）
- ✅ 需求澄清循环（最多 3 轮）
- ✅ 基于画像的框架生成（分段输出）
- ✅ 长期记忆读写
- ✅ 情景记忆存储与检索
- ✅ 完整任务流程演示（demo.py）
- ✅ 画像更新演示（反馈修改字段）

## 接 LLM（LangChain 可选）

当前方案生成由规则引擎完成，保证无 API Key 也能跑。要接入真实大模型：

```bash
pip install langchain langchain-openai openai
```

在 `waibao/llm.py` 的 `LangChainAdapter.generate()` 中实现 prompt 模板
（把 `spec` 任务规格书和 `profile` 画像快照组装成提示词），
然后 `PersonalExplorerAgent(llm=LangChainAdapter(enabled=True))`。

## 托管到 GitHub

先确认认证方式（二选一）：

**方式 A：Personal Access Token（推荐快速上手）**
1. 到 https://github.com/settings/tokens 创建 Fine-grained PAT，
   勾选 Repositories → Contents 读写权限
2. 把 token 告诉 Codex（会话内使用，不写入代码）

**方式 B：SSH 密钥**
1. 让 Codex 生成密钥，把公钥添加到 https://github.com/settings/keys
2. 之后用 SSH 方式推送

然后执行：

```bash
git init
git add .
git commit -m "feat: 外脑伙伴最小原型 v2"
git branch -M main
git remote add origin <仓库地址>
git push -u origin main
```

仓库内置 `.github/workflows/demo.yml`：每次 push 自动跑 `python3 demo.py` 冒烟测试。

