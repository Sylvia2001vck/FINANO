import { BulbOutlined } from "@ant-design/icons";
import { Button, Card, Input, List, Space, Switch, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { getAgentProfile } from "../../services/agent";
import {
  getFbtiProfile,
  postFbtiAiIntentPreview,
  postFbtiAiSelectStream,
  type FbtiIntentPreview,
  type FbtiSelectResponse
} from "../../services/fbti";

const WX_COLOR: Record<string, string> = {
  金: "gold",
  木: "green",
  水: "blue",
  火: "red",
  土: "orange"
};

function WuxingBadge({ text }: { text: string }) {
  const first = text[0]?.replace(/[^\u4e00-\u9fff]/g, "") || text;
  const color = WX_COLOR[first] || "default";
  return (
    <Tag color={color} style={{ fontSize: 14 }}>
      {text}
    </Tag>
  );
}

/** 独立模块：AI娱乐选基（与 MAFB、用户与社区解耦） */
export default function AiFundPickPage() {
  const [loading, setLoading] = useState(true);
  const [hasFbti, setHasFbti] = useState(false);
  const [hasBirthProfile, setHasBirthProfile] = useState(false);
  const [ai, setAi] = useState<FbtiSelectResponse | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiStage, setAiStage] = useState<string>("");
  const [naturalIntent, setNaturalIntent] = useState("");
  const [mood, setMood] = useState("");
  const [autoConfirm, setAutoConfirm] = useState(false);
  const [preview, setPreview] = useState<FbtiIntentPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [stageLog, setStageLog] = useState<string[]>([]);

  useEffect(() => {
    let done = 0;
    const markDone = () => {
      done += 1;
      if (done >= 2) setLoading(false);
    };
    void getFbtiProfile()
      .then((d) => {
        setHasFbti(Boolean(d.fbti_profile));
      })
      .catch(() => setHasFbti(false))
      .finally(markDone);
    void getAgentProfile()
      .then((res) => {
        const raw = res?.saved_fields as Record<string, unknown> | null | undefined;
        setHasBirthProfile(Boolean(raw?.birth_date));
      })
      .catch(() => setHasBirthProfile(false))
      .finally(markDone);
  }, []);

  const buildPayload = () => ({
    natural_intent: naturalIntent.trim() || undefined,
    mood: mood.trim() || undefined,
    auto_confirm: autoConfirm
  });

  const runPreview = async () => {
    setPreviewLoading(true);
    try {
      const p = await postFbtiAiIntentPreview(buildPayload());
      setPreview(p);
      message.success("已生成意图与策略预览");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "预览生成失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const runAi = async () => {
    setAiLoading(true);
    setAiStage("连接服务…");
    setStageLog([]);
    try {
      const r = await postFbtiAiSelectStream({
        onStage: (_node, label) => {
          setAiStage(label);
          setStageLog((prev) => [...prev, label].slice(-12));
        },
        onBazi: (payload) =>
          setPreview((prev) => ({ ...(prev || { intent: {}, strategy_bundle: {}, need_confirm: true }), bazi_analysis: payload })),
        onIntent: (payload) => setPreview((prev) => ({ ...(prev || { strategy_bundle: {}, need_confirm: true }), intent: payload })),
        onStrategy: (payload) => setPreview((prev) => ({ ...(prev || { intent: {}, need_confirm: true }), strategy_bundle: payload })),
      }, buildPayload());
      setAi(r);
      setAiStage("");
      message.success("已生成娱乐向组合建议");
    } catch (e) {
      setAiStage("");
      message.error(e instanceof Error ? e.message : "请求失败");
    } finally {
      setAiLoading(false);
    }
  };

  if (loading) {
    return <Typography.Paragraph>加载中…</Typography.Paragraph>;
  }

  const canRun = hasFbti || hasBirthProfile;

  return (
    <div className="page-stack">
      <Typography.Title level={3}>AI娱乐选基</Typography.Title>
      <Typography.Paragraph type="secondary">
        一键流程：自动读取用户档案中的生日/出生时段推算八字，再做今日时势解读 → 金融意图翻译 → 策略关联 → 基金终筛；
        若已完成 FBTI，会自动叠加人格画像。
        该模块与 MAFB 解耦，仅用于自然语言策略设计与趣味向选基，不构成投资建议。
      </Typography.Paragraph>
      <PageCard title="一键生成（娱乐向）">
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input.TextArea
            rows={2}
            value={naturalIntent}
            onChange={(e) => setNaturalIntent(e.target.value)}
            placeholder="自然语言策略意图（例：今天偏科技成长，但控制回撤）"
          />
          <Input
            value={mood}
            onChange={(e) => setMood(e.target.value)}
            placeholder="当前情绪（例：谨慎 / 激进 / 怕回撤）"
          />
          <Space wrap>
            <Typography.Text type="secondary">自动确认执行</Typography.Text>
            <Switch checked={autoConfirm} onChange={setAutoConfirm} />
            <Button loading={previewLoading} onClick={() => void runPreview()}>
              预览意图与策略
            </Button>
          </Space>
          <Button type="primary" icon={<BulbOutlined />} loading={aiLoading} disabled={!canRun} onClick={() => void runAi()}>
            开始流式执行
          </Button>
          {!hasFbti ? (
            <Typography.Text type="secondary">
              未检测到 FBTI 画像：会仅按生日/出生时段推算八字执行；如需叠加人格，请先完成 <Link to="/user-community#fbti">FBTI 测试</Link>。
            </Typography.Text>
          ) : null}
          {!hasBirthProfile ? (
            <Typography.Text type="warning">
              尚未在 <Link to="/user-community#profile">用户档案</Link> 中保存生日信息（可选出生时段），暂无法自动推算八字。
            </Typography.Text>
          ) : null}
          {aiLoading && aiStage ? <Typography.Text type="secondary">{aiStage}</Typography.Text> : null}
          {stageLog.length ? (
            <List
              size="small"
              bordered
              dataSource={stageLog}
              renderItem={(line) => <List.Item>{line}</List.Item>}
            />
          ) : null}
        </Space>
        {preview ? (
          <Card size="small" style={{ marginTop: 16 }} title="意图与策略预览">
            <Typography.Paragraph style={{ marginBottom: 8 }}>
              need_confirm: <Tag color={preview.need_confirm ? "gold" : "green"}>{String(preview.need_confirm)}</Tag>
            </Typography.Paragraph>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              八字解读：{JSON.stringify(preview.bazi_analysis || {}, null, 2)}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              意图：{JSON.stringify(preview.intent || {}, null, 2)}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
              策略：{JSON.stringify(preview.strategy_bundle || {}, null, 2)}
            </Typography.Paragraph>
          </Card>
        ) : null}
        {ai && (
          <Card size="small" style={{ marginTop: 16 }} title="说明与结果">
            <Typography.Paragraph>{ai.reason}</Typography.Paragraph>
            <List
              bordered
              dataSource={ai.funds}
              renderItem={(item) => (
                <List.Item>
                  <Space>
                    <Typography.Text code>{item.code}</Typography.Text>
                    <Typography.Text>{item.name}</Typography.Text>
                    <WuxingBadge text={item.wuxing_tag} />
                    <Typography.Text type="secondary">{item.change_hint}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        )}
      </PageCard>
      <Link to="/user-community#fbti">查看 FBTI 人格详情（用户与社区）</Link>
    </div>
  );
}
