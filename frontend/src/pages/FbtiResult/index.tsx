import { Button, Card, Space, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { getFbtiProfile, type FbtiArchetype } from "../../services/fbti";

export default function FbtiResultPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [arch, setArch] = useState<FbtiArchetype | null>(null);
  const [code, setCode] = useState<string | null>(null);
  useEffect(() => {
    void getFbtiProfile()
      .then((d) => {
        setCode(d.fbti_profile);
        setArch(d.archetype);
      })
      .catch(() => message.warning("请先完成测试"))
      .finally(() => setLoading(false));
  }, []);

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
      <Space style={{ marginBottom: 16 }} wrap>
        <Button onClick={() => navigate("/fbti-test?retake=1")}>重新测试</Button>
      </Space>
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
              <Typography.Paragraph>
                {arch.description || arch.blurb}
              </Typography.Paragraph>
              {arch.risk_level ? (
                <Typography.Text type="secondary">风险档位（演示）：{arch.risk_level}</Typography.Text>
              ) : null}
              {arch.fund_preference ? (
                <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                  选股偏好：{arch.fund_preference}
                </Typography.Paragraph>
              ) : null}
              <Space wrap>
                {(arch.tags || arch.style_tags || []).map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </Space>
            </>
          )}
        </Space>
      </Card>
    </div>
  );
}
