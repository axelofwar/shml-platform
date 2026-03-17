---
name: web-search
description: Search the web for information using DuckDuckGo. Use when the user asks to search for something, research a topic, find documentation, or look up current information. Privacy-focused with no tracking.
license: MIT
compatibility: Requires internet access. Uses DuckDuckGo API.
metadata:
  author: shml-platform
  version: "1.0"
---

# Web Search Skill

## When to use this skill
Use this skill when the user asks to:
- Search for information
- Research a topic
- Find documentation
- Look up best practices
- Get current/recent information

## Operations

### search
Search the web and return relevant results.

**Parameters:**
- `query` (required): Search query string
- `max_results` (optional): Number of results (default: 5, max: 10)

**Example:**
```python
result = await execute("search", {
    "query": "PyTorch distributed training best practices 2024",
    "max_results": 5
})
```

**Response:**
```json
{
  "query": "PyTorch distributed training",
  "results": [
    {
      "title": "Distributed Training with PyTorch",
      "url": "https://pytorch.org/tutorials/...",
      "snippet": "Learn how to use DistributedDataParallel..."
    }
  ],
  "count": 5
}
```

## Best Practices

1. **Be specific**: Include year or version for technical queries
2. **Use keywords**: "Python asyncio tutorial" vs "how to do async in python"
3. **Limit results**: 5 is usually enough, don't ask for 100

## Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| No results | Query too specific | Broaden search terms |
| Timeout | Network issue | Retry with shorter query |
| Rate limit | Too many requests | Wait and retry |

## Privacy

DuckDuckGo doesn't track searches. Results are:
- Not personalized
- Not logged
- Not used for advertising
