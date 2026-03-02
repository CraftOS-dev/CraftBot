---
name: ai-news-collector
description: AI 新闻聚合与热度排序工具。当用户询问 AI 领域最新动态时触发，如："今天有什么 AI 新闻？""总结一下这周的 AI 动态""最近有什么火的 AI 产品？""AI 圈最近在讨论什么？"。覆盖：新产品发布、研究论文、行业动态、融资新闻、开源项目更新、社区病毒传播现象、AI 工具/Agent 热门项目。输出中文摘要列表，按热度排序，附带原文链接。
---

# AI News Collector

收集、聚合并按热度排序 AI 领域新闻。

## 核心原则

**不要只搜"AI news today"。** 泛搜索返回的是 SEO 聚合页和趋势预测文章，会系统性遗漏社区级病毒传播现象（如开源工具爆火、Meme 级事件）。必须用多维度、分层搜索策略。

## 工作流程

### 1. 多维度分层搜索（最少 8 次，建议 10-12 次）

按以下 **6 个维度** 依次执行搜索，每个维度至少 1 次：

#### 维度 A：周报/Newsletter 聚合（最优先 🔑）

这是信息密度最高的来源，一篇文章可覆盖 10+ 条新闻。

```
搜索词：
- "last week in AI" [当前月份年份]
- "AI weekly roundup" [当前月份年份]
- "the batch AI newsletter"
- site:substack.com AI news [当前月份]
```

发现周报后，用 web_fetch 获取全文，从中提取所有新闻线索。

#### 维度 B：社区热度/病毒传播（关键维度 🔑）

捕捉自下而上的社区爆款，这类信息泛搜索几乎无法触达。

```
搜索词：
- "viral AI tool" OR "viral AI agent"
- "AI trending" site:reddit.com OR site:news.ycombinator.com
- "GitHub trending AI" OR "AI open source trending"
- AI buzzing OR "everyone is talking about" AI
- "most popular AI" this week
```

#### 维度 C：产品发布与模型更新

```
搜索词：
- "AI model release" OR "LLM launch" [当前月份]
- "AI product launch" [当前月份年份]
- OpenAI OR Anthropic OR Google OR Meta AI announcement
- "大模型 发布" OR "AI 新产品"
```

#### 维度 D：融资与商业

```
搜索词：
- "AI startup funding" [当前月份年份]
- "AI acquisition" OR "AI IPO"
- "AI 融资" OR "人工智能投资"
```

#### 维度 E：研究突破

```
搜索词：
- "AI breakthrough" OR "AI paper" [当前月份]
- "state of the art" machine learning
- "AI 论文" OR "机器学习突破"
```

#### 维度 F：监管与政策

```
搜索词：
- "AI regulation" OR "AI policy" [当前月份年份]
- "AI law" OR "AI governance" 
- "AI 监管" OR "人工智能法案"
```

### 2. 交叉验证与补漏

初轮搜索完成后，检查是否有遗漏：

- 如果 Newsletter 中提到了某个项目/事件但初轮搜索未覆盖 → 对该项目专项搜索
- 如果同一事件被 3+ 个不同来源提及 → 大概率是热点，深入搜索获取更多细节
- 如果中文媒体和英文媒体的热点完全不同 → 两边都要覆盖

### 3. 搜索关键词设计原则（反模式清单）

| ❌ 不要这样搜 | ✅ 应该这样搜 | 原因 |
|---|---|---|
| "AI news today February 2026" | "AI weekly roundup February 2026" | 前者返回聚合页，后者返回策划内容 |
| "AI news today" | "viral AI tool" + "AI model release" 分开搜 | 泛搜无法覆盖社区现象 |
| "artificial intelligence breaking news" | 按维度分类搜索 | 过于宽泛，返回噪音 |
| 搜索词中加具体年月日 | 用 "this week" "today" "latest" | 日期反而会偏向预测/展望文章 |
| 只搜 3 次就开始写 | 至少 8 次，覆盖 6 个维度 | 3 次搜索覆盖率不到 30% |

### 4. 热度综合判断

基于以下信号评估每条新闻热度（1-5 星）：

| 信号 | 权重 | 说明 |
|------|------|------|
| 多家媒体报道同一事件 | ⭐⭐⭐ 高 | 3+ 来源 = 确认热点 |
| 社区病毒传播证据 | ⭐⭐⭐ 高 | GitHub star 暴涨、Twitter 刷屏、HN 首页 |
| 来自权威来源（顶会、大厂官宣） | ⭐⭐⭐ 高 | 但注意大厂 PR 不等于真热点 |
| 实际用户体验分享 | ⭐⭐ 中 | 有人真的在用 > 只是发布了 |
| 技术突破性/影响范围 | ⭐⭐ 中 | |
| 争议性（安全、伦理讨论） | ⭐⭐ 中 | 争议往往说明影响力大 |
| 时效性（越新越热） | ⭐ 中低 | 辅助排序 |

### 5. 输出格式

按热度降序排列，输出 **15-25 条**新闻：

```
## 🔥 AI 新闻速递（YYYY-MM-DD）

### ⭐⭐⭐⭐⭐ 热度最高

1. **[新闻标题]**
   > 一句话摘要（不超过 50 字）
   > 🔗 [来源名称](URL)

### ⭐⭐⭐⭐ 高热度

2. ...

### ⭐⭐⭐ 中等热度

...

---
📊 本次共收集 XX 条新闻 | 搜索 XX 次 | 覆盖维度：A/B/C/D/E/F | 更新时间：HH:MM
```

### 6. 去重与合并

- 同一事件被多家报道时，合并为一条，选择最权威/详细的来源
- 在摘要中注明"多家媒体报道"以体现热度
- 改名/更名的项目视为同一事件（如 Clawdbot → Moltbot → OpenClaw）

## 推荐新闻源

详见 [references/sources.md](references/sources.md)。

## 注意事项

- 优先使用 HTTPS 链接
- 遇到付费墙/无法访问的内容，标注"需订阅"
- 保持客观，不对新闻内容做主观评价
- 搜索不足 8 次不要开始输出
- 如果某个维度搜索结果为空，换关键词再搜一次
