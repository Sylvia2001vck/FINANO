import { BulbOutlined } from "@ant-design/icons";
import { Button, Card, List, Space, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { getFbtiProfile, postFbtiAiSelect, type FbtiArchetype, type FbtiSelectResponse } from "../../services/fbti";

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

export default function FbtiResultPage() {
  const [loading, setLoading] = useState(true);
  const [arch, setArch] = useState<FbtiArchetype | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [wx, setWx] = useState<string | null>(null);
  const [birth, setBirth] = useState<string | null>(null);
  const [ai, setAi] = useState<FbtiSelectResponse | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  useEffect(() => {
    void getFbtiProfile()
      .then((d) => {
        setCode(d.fbti_profile);
        setWx(d.user_wuxing);
        setBirth(d.birth_date);
        setArch(d.archetype);
      })
      .catch(() => message.warning("请先完成测试"))
      .finally(() => setLoading(false));
  }, []);

  const runAi = async () => {
    setAiLoading(true);
    try {
      const r = await postFbtiAiSelect();
      setAi(r);
      message.success("已生成组合建议");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "请求失败");
    } finally {
      setAiLoading(false);
    }
  };

  if (loading) {
    return <Typography.Paragraph>加载中…</Typography.Paragraph>;
  }

  if (!code) {
    return (
      <PageCard title="尚未完成 FBTI">
        <Typography.Paragraph>请先完成测试。</Typography.Paragraph>
        <Link to="/fbti-test">
          <Button type="primary">去测试</Button>
        </Link>
      </PageCard>
    );
  }

  return (
    <div className="page-stack">
      <Typography.Title level={3}>你的 FBTI 金融人格</Typography.Title>
      <Card>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Typography.Text type="secondary">代码 </Typography.Text>
            <Typography.Text code style={{ fontSize: 22 }}>
              {code}
            </Typography.Text>
          </div>
          {arch && (
            <>
              <Typography.Title level={4} style={{ margin: 0 }}>
                {arch.name}
                {arch.nearest_archetype ? (
                  <Typography.Text type="secondary">（最近归档）</Typography.Text>
                ) : null}
              </Typography.Title>
              <Typography.Paragraph>{arch.blurb}</Typography.Paragraph>
              <Space wrap>
                {(arch.tags || []).map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </Space>
            </>
          )}
          <div>
            <Typography.Text>五行偏好：</Typography.Text>{" "}
            {wx ? <WuxingBadge text={wx} /> : <Tag>—</Tag>}
          </div>
          {birth ? (
            <Typography.Text type="secondary">生日：{birth}</Typography.Text>
          ) : null}
        </Space>
      </Card>

      <PageCard title="一键 AI 选股">
        <Typography.Paragraph type="secondary">
          结合 DashScope 与演示基金池（含可选实时行情），输出 JSON 组合建议；无 Key 时自动规则兜底。
        </Typography.Paragraph>
        <Button type="primary" icon={<BulbOutlined />} loading={aiLoading} onClick={() => void runAi()}>
          一键 AI 选股
        </Button>
        {ai && (
          <Card size="small" style={{ marginTop: 16 }} title="说明">
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

      <PageCard title="下一步">
        <Space>
          <Link to="/fbti-test">
            <Button>重新测试</Button>
          </Link>
          <Link to="/trade">
            <Button type="link">去交易记录（自选演示）</Button>
          </Link>
        </Space>
      </PageCard>
    </div>
  );
}
