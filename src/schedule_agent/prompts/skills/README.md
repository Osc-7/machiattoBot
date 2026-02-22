# 可选技能 (Optional Skills)

本目录用于存放可复用的 Agent 技能，通过 `config.skills.enabled` 配置 load/unload。

## 添加技能

1. 新建目录：`skills/{skill-name}/`
2. 创建 `SKILL.md`，符合 [AgentSkills](https://agentskills.io/) 规范：
   - YAML frontmatter 含 `name`、`description`
   - Markdown 正文为技能说明
3. 在 `config.yaml` 中启用：`skills.enabled: [skill-name]`

## 示例结构

```
skills/
  my-skill/
    SKILL.md
```
