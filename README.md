# ayh-wd — 爱优护轻便侠 218 电动轮椅 H3 视频生成（主图视频 + 推广视频）

基于 AutoDL.Art MiniMax H3 视频生成 API，为「爱优护 Ainsnbot 轻便侠 218 电动轮椅」生成电商主图视频与推广视频。独立于仓库的 `autodl` 技能（那个是佳康顺折叠轮椅软广），本技能产品、提示词模板、参考图全部独立。

## 功能

- **10 秒 1080P 视频生成**：主图视频（纯产品展示）+ 推广视频（人物场景软广）
- **卖点全量沉淀**：轻便(13.8kg)/安全(3.0防翻+电磁刹车)/舒适(145°后躺+减震)/智能(手机遥控+语音播报) 四大卖点体系，均 OCR 自官方详情页
- **高清参考图**：`D:\BaiduSyncdisk\10 产品高清图\爱优护详情页\轻便侠 218\`（正侧/折叠/后躺/45度带头枕，白底无人物，决定产品外观）

## 快速开始

```bash
cd "C:/Users/20200/AppData/Local/hermes/skills/ayh-wd/scripts"
python h3_gen.py -w multi_image --prompt "提示词" \
  -i "D:/BaiduSyncdisk/10 产品高清图/爱优护详情页/轻便侠 218/正侧-3-无阴影.png" \
  -i "D:/BaiduSyncdisk/10 产品高清图/爱优护详情页/轻便侠 218/折叠-无阴影.png" \
  -r 1080p竖 -d 10 -o 主图视频1.mp4
```

## API 速查

| 项目 | 值 |
|---|---|
| Base URL | `https://autodl.art` |
| 提交 | `POST /api/v1/comfyui/comfyui_workflow/{workflow_id}` |
| 轮询 | `GET /api/v1/comfyui/comfyui_workflow/result/{task_id}`（⚠️ 必须 GET） |
| 鉴权 | `Authorization: <token>`（token 在 `scripts/.env`） |
| 价格 | 480p ¥0.04/s · 768p ¥0.06/s · 1080p ¥0.10/s |

## 目录

- `SKILL.md` — 完整技能文档（卖点、提示词规则 v1、10 个现成提示词）
- `scripts/h3_gen.py` — 通用单条生成客户端（multi_image/image_audio/text2video/first_last）
- `scripts/.env` — AUTODL_API_KEY（勿提交 GitHub，仓库公开）

## License

MIT
