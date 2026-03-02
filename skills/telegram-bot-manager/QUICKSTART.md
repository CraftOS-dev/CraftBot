# Telegram Bot Manager - 快速开始指南

## 🚀 快速开始

### 1. 获取机器人令牌

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 命令
3. 按照提示创建机器人
4. 复制机器人令牌（格式：`1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`）

### 2. 运行自动设置脚本

```bash
cd /home/openclaw/.openclaw/workspace/telegram-bot-manager
python3 scripts/setup_bot.py
```

按照提示输入你的机器人令牌，脚本会自动：
- 备份现有配置
- 更新 OpenClaw 配置
- 重启 OpenClaw 网关

### 3. 测试机器人

```bash
# 使用环境变量
export TELEGRAM_BOT_TOKEN="你的机器人令牌"
python3 scripts/test_bot.py

# 或者直接传递令牌
python3 scripts/test_bot.py "你的机器人令牌"
```

### 4. 在 Telegram 中激活

1. 在 Telegram 中搜索你的机器人用户名
2. 发送 `/start` 开始对话
3. 按照机器人提供的配对说明操作

## 🔧 手动配置

如果自动设置脚本不工作，可以手动配置：

### 编辑 OpenClaw 配置

编辑文件：`/home/openclaw/.openclaw/openclaw.json`

```json
{
  "telegram": {
    "enabled": true,
    "token": "你的机器人令牌",
    "pairing": true,
    "streamMode": "partial"
  },
  "plugins": ["telegram"]
}
```

### 重启 OpenClaw

```bash
openclaw gateway restart
```

## 🐛 常见问题

### 无法访问 api.telegram.org

```bash
# 测试连接
curl -I https://api.telegram.org

# 检查 DNS
nslookup api.telegram.org
```

### 机器人不响应

1. 检查令牌是否正确（没有多余空格）
2. 确认机器人已启用
3. 重启 OpenClaw 网关

### 配对问题

1. 确保配置中 `pairing: true`
2. 检查机器人隐私设置
3. 确认机器人未被屏蔽

## 📚 更多文档

- **详细配置**：`references/OPENCLAW_CONFIG.md`
- **Webhook 设置**：`references/WEBHOOK_SETUP.md`
- **完整说明**：`README.md`

## 🛡️ 安全提醒

- 永远不要将机器人令牌提交到版本控制
- 使用环境变量存储令牌
- 定期轮换令牌
- 监控机器人活动

## 📦 发布到 ClawHub

```bash
# 打包技能
python3 scripts/package_skill.py .

# 登录 ClawHub
clawhub login

# 发布
clawhub publish . \
  --slug telegram-bot-manager \
  --name "Telegram Bot Manager" \
  --version 1.0.0 \
  --changelog "初始版本"
```

## 🎯 下一步

1. ✅ 测试基本功能
2. 🔄 配置 Webhook（生产环境）
3. 📊 监控机器人使用情况
4. 🔄 定期更新技能

---

**提示**：如果遇到问题，请查看 `references/` 文件夹中的详细指南。
