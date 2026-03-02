---
name: ai-ppt-generator
description: The awesome PPT format generation tool provided by baidu.
metadata: { "emoji": "📑", "requires": { "bins": ["python3"], "env":["BAIDU_API_KEY"]}, "primaryEnv":"BAIDU_API_KEY" }
---

# AI PPT Generation
Using user input topic/query, generate a high-quality PPT download URL via Baidu AI's streaming API.

## Important: Streaming Timeout Behavior
This skill uses **streaming HTTP requests** that can take **2+ minutes** to complete. Default timeouts may interrupt the stream before completion.

To ensure successful generation:
1. **The agent must wait for the full stream** until `is_end: true` is received
2. **Do NOT rely on immediate completion** – monitor the streaming response
3. **If timeout occurs**, the skill will appear to fail even though generation continues server-side

## Workflow
1. Execute `scripts/generate_ppt.py` with user query
2. **Wait for streaming completion** (2+ minutes typical)
3. Return final PPT URL when `is_end: true` received

### Expected Output Format
Successful completion returns:
```json
{
  "status": "PPT导出结束",
  "show_msg": "PPT导出成功",
  "is_end": true,
  "data": {
    "ppt_url": "https://...ppt"
  }
}
```

During generation, you'll see interim `{"status": "..."}` messages.

### Example Usage
```bash
python3 scripts/generate_ppt.py --query "经济总结报告ppt"
```

## Agent Instructions
When using this skill:
- **Set appropriate timeout**: Ensure exec/sessions have sufficient timeout (180+ seconds)
- **Monitor streaming output**: Don't assume failure if initial responses only show status
- **Wait for completion**: The final URL only appears at stream end with `is_end: true`
- **Handle gracefully**: If interrupted, inform user generation may continue server-side

## Troubleshooting
- **PPT not appearing**: Likely timeout before stream completion
- **Only status messages**: Generation is in progress, wait longer
- **Script exits early**: Check BAIDU_API_KEY and network connectivity
