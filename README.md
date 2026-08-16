# 外脑伙伴（最小原型 v2）

一个基于用户画像、具备持续自主优化能力的“探索-生成”型 AI Agent 最小原型。
严格按规格说明书实现四个一级模块，零第三方依赖即可运行。

## 运行

```bash
cd waibao_partner_agent
python3 demo.py    # 全自动演示（结构化任务流程：澄清→规格→四阶段交付）
python3 chat.py    # 真人在终端交互；接 LLM 后是 ChatGPT 式自然对话（带画像/多轮/流式）
python3 llm_test.py  # LLM 连通性自检（换 Key 后先跑这个确认）
./run_web.sh       # 网页版（Streamlit，首次自动安装依赖并打开浏览器）
```

`chat.py` 有两种模式：设了 LLM Key 时是「自然对话模式」（像 ChatGPT 一样
连续多轮聊、逐字流式输出、默默学习你的偏好）；没设 Key 时退回
「结构化任务流程」（澄清 → 规格确认 → 框架/内容/成品四阶段交付）。

`chat.py` 支持命令：`查看画像`、`调整画像`、`查看历史`、`接着做`。

## 网页版与工具

网页版（`streamlit run app.py`，或双击 `启动网页.command` / 运行 `./run_web.sh`）：
聊天式界面 + 流式输出 + 侧边栏画像 + 一键清空/重置记忆。

在对话里直接说以下指令即可触发工具：

- `搜索 <关键词>`：联网搜索（需设置 `TAVILY_API_KEY`，https://tavily.com 有免费额度）
- `搜索文件 <关键词>`：按文件名在允许目录内查找
- `搜索内容 <关键词>`：按文本内容在允许目录内查找
- `读文件 <路径>`：读取允许目录内的文本文件
- `列出文件`：列出目录内容
- `运行 <命令>`：执行命令（默认关闭，见下方「文件访问与执行安全」）

跨重启对话历史：`chat.py` 和网页版都会把对话保存到 `waibao_data/conversation_history.json`，
下次打开接着聊。

图片多模态：代码已留 `LLMAdapter.supports_vision` 钩子；当前 DeepSeek-chat 不支持图片，
换成 OpenAI 视觉模型（如 gpt-4o）后即可启用图片上传。

## 文件访问与执行安全

默认情况下，文件工具只允许访问**项目目录**，不会碰到你电脑其他位置；执行命令功能**默认关闭**。这是刻意的安全设计。

如需让 agent 访问更大的范围（例如你自己的 `~/Documents`），在项目 `.env` 里加一行：

```bash
WAIBao_ALLOWED_ROOT=~/Documents
```

如需开启「运行命令」能力（请只在**本机自己使用**时开启）：

```bash
WAIBao_ENABLE_EXEC=1
```

开启后，你说「运行 某条命令」，agent 会先把命令显示出来、请你回复「确认」后才真正执行，并有 30 秒超时限制。

> ⚠️ 公开分享链接（Streamlit Cloud）请**不要**开启 `WAIBao_ENABLE_EXEC`，否则任何打开链接的人都能在你部署的服务器上执行命令；云端服务器也访问不到你本机的文件。

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

## 接真实 LLM（OpenAI 兼容接口，支持 OpenAI / DeepSeek / Anthropic 中转）

方案生成默认由规则引擎完成，保证无 Key 也能跑。要换成真实大模型，
只需设置环境变量（零第三方依赖，用标准库直接调兼容接口）：

```bash
export LLM_PROVIDER=deepseek            # openai / deepseek / usegoodai
export LLM_API_KEY=你的密钥
# 可选：export LLM_MODEL=deepseek-chat   # 覆盖默认模型

python3 chat.py                         # 此时会自动启用真实 LLM
```

也支持任意 OpenAI 兼容端点（如 Anthropic 中转）：

```bash
export LLM_BASE_URL=https://api.usegoodai.com/v1
export LLM_API_KEY=你的密钥
export LLM_MODEL=claude-3-7-sonnet-20250219
```

密钥读取顺序：`LLM_API_KEY` → `OPENAI_API_KEY` → `DEEPSEEK_API_KEY` →
`ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY`。

也可以在代码里显式传入：

```python
from waibao.llm import LLMAdapter
from waibao.agent import PersonalExplorerAgent

llm = LLMAdapter(provider="deepseek", api_key="sk-...", enabled=True)
agent = PersonalExplorerAgent(storage_dir="waibao_data", llm=llm)
```

`LLMAdapter` 会把用户画像快照、任务规格书、交付阶段和画像约束一起组装进
prompt（宏观先行、结构化、少举例、红线规避、分段交付等），
未配置 Key 或 `enabled=False` 时自动回退规则引擎。

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

## 部署成公开链接（任何人任何设备可打开）

`localhost:8501` 只有本机能访问；要让任何人在手机上点开，需部署到云端。
免费方案：Streamlit Community Cloud（https://share.streamlit.io）。

步骤：

1. 把 GitHub 仓库设为 Public（Settings → General → Danger Zone → Change visibility）。
2. 打开 https://share.streamlit.io → New app → 用 GitHub 登录并授权。
3. 选择仓库 `waibao-partner-agent`，Main file path 填 `app.py`。
4. 在 Advanced settings 的 Secrets 里填：
   ```
   LLM_PROVIDER = "deepseek"
   LLM_API_KEY = "sk-你的密钥"
   ```
5. 点 Deploy，得到 `https://xxx.streamlit.app` 公开链接。

注意：

- 公开链接意味着任何人打开都会消耗你的 DeepSeek 额度，建议演示时用小额度 Key。
- 可在 Secrets 里加 `ACCESS_PASSWORD = "你的密码"`，给网页加一道密码，防止陌生人滥用额度。
- 免费云端的 `waibao_data/` 是临时的，重启后会清空；要长期保留记忆需再接一个免费数据库。
- `读文件/列目录` 在云端只作用于仓库文件，不会碰到你本机文件；`联网搜索` 需再配 `TAVILY_API_KEY`。

## 账号系统（跨设备保存历史）

默认情况下，云端是「每个浏览器会话独立」，换设备或清缓存就会丢失历史。要「登录账号、跨设备找回自己的画像和聊天历史」，需要接入 Supabase（免费）。

### 一次性配置

1. 注册并登录 https://supabase.com，新建一个项目。
2. 关闭邮箱验证（否则注册后要先去邮箱点确认）：Authentication → Providers → Email → 关闭 `Confirm email`。
3. 建表：SQL Editor → New query → 粘贴 `supabase_setup.sql` 全部内容 → Run。
4. 拿连接信息：Project Settings → API → 复制 `Project URL` 和 `anon public` 两个值。
5. 填到云端 Secrets（本地则填到 `.env`）：

   ```bash
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_ANON_KEY = "eyJ..."
   ```

6. 重新部署（云端）或重启网页（本机）。

配置后，打开网页会先出现登录/注册页；每个账号的画像、记忆、聊天历史、归档对话都会跨设备保存在云端。

> 说明：Supabase 免费额度足够作品集演示使用；密码由 Supabase 托管加密存储，代码里不接触明文。
