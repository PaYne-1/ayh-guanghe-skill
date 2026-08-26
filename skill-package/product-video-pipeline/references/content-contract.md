# 内容生成契约

文本模型必须输出结构化 JSON，不把自由文本直接交给后续节点。每条只含一个核心卖点。

## 必填字段

```json
{
  "video_id": "V001",
  "selling_point": "操作简单",
  "core_idea": "一句话核心创意",
  "audience": "适用人群",
  "scene": "使用场景",
  "pain_point": "核心痛点",
  "angle": "卖点切入角度",
  "topic": "选题方向",
  "publish_title": "约20个汉字且含电动轮椅",
  "cover_title": "约4至6个汉字",
  "people": [
    {
      "id": "P1",
      "identity": "老人",
      "gender": "女",
      "age_feel": "70岁左右",
      "position": "画面左侧坐在轮椅上",
      "action": "手放控制器上",
      "speaks": true
    }
  ],
  "closing_speaker_id": "P1",
  "storyboard_people": ["P1"],
  "script_segments": [
    {"start": 0, "end": 4, "speaker_id": "P2", "dialogue": "一个购买前问题"},
    {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "围绕唯一卖点的真实回答"},
    {"start": 11, "end": 15, "speaker_id": "P1", "dialogue": "用了产品后+具体改善+柔和购买引导"}
  ],
  "storyboard_prompt": "唯一分镜图提示词",
  "video_prompt": "15秒一镜到底视频提示词",
  "final_feeling": "最终成片感觉",
  "filming_advice": "真人实拍建议",
  "publish_body": "80至150个汉字正文",
  "hashtags": ["固定标签"]
}
```

## 生成规则

- 先分析适用人群和使用场景，再得出痛点、切入角度与选题；不判断疾病、伤情或康复效果。
- 发布标题只生成一个，约 20 个汉字，标题党风格但语义顺畅、不夸张。爱优护配置只强制包含“电动轮椅”，不强制品牌名。
- 封面标题从发布标题的痛点或益处压缩得到，约 4–6 个汉字，不要求包含“电动轮椅”。
- 默认优先 2 人；确有必要才用 3 人。所有说话人必须在画面中，无画外音。
- 人物 ID、身份、性别、年龄感、站位、动作在脚本、分镜和视频提示词中逐项一致。
- 0–4 秒只提出一个购买前问题；4–11 秒只回答唯一卖点；11–15 秒必须同时完成“买了/用了/换了产品后 + 具体改善益处 + 柔和购买引导”。
- 口播按正常聊天语速能在 15 秒左右说完。不要堆参数、堆卖点或加入未提供的重量、续航、价格、材质、专利和认证。

## 校验与落盘

```powershell
python scripts/workflow_cli.py validate-content `
  --item-dir "批次/V001_卖点_待生成" `
  --content "content.json" `
  --profile "profiles/爱优护电动轮椅_淘宝天猫光合.json"
```

校验失败时修改内容 JSON，再运行；不要绕过校验直接提交视频。
