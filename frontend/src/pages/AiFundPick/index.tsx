import { BulbOutlined } from "@ant-design/icons";
import { Button, Card, List, Space, Table, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { getFbtiProfile, postFbtiAiSelect, type FbtiSelectResponse } from "../../services/fbti";

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

/** 侧栏「AI 选股」：仅 FBTI 一键选股，与 MAFB 控制台解耦 */
export default function AiFundPickPage() {
  const [loading, setLoading] = useState(true);
  const [hasFbti, setHasFbti] = useState(false);
  const [ai, setAi] = useState<FbtiSelectResponse | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  useEffect(() => {
    void getFbtiProfile()
      .then((d) => {
        setHasFbti(Boolean(d.fbti_profile));
      })
      .catch(() => setHasFbti(false))
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

  if (!hasFbti) {
    return (
      <div className="page-stack">
        <Typography.Title level={3}>AI 选股（FBTI）</Typography.Title>
        <PageCard title="需要先完成 FBTI">
          <Typography.Paragraph>
            本功能根据你的金融人格与基金目录做语义筛选。请先到「<Link to="/fbti-result">FBTI 画像</Link>」完成测试。
          </Typography.Paragraph>
        </PageCard>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <Typography.Title level={3}>AI 选股（FBTI）</Typography.Title>
      <Typography.Paragraph type="secondary">
        多阶段：偏好归纳（含五行娱乐维度）→ 随机抽样与规则 Top20 → 大模型终筛至多 5 只；无 Key 时规则兜底。
        与 MAFB 控制台解耦：MAFB 画像仅基于 FBTI；本页的「个性化 TOP5」为八字五行流年与统计融合的趣味展示。
      </Typography.Paragraph>
      <PageCard title="一键生成">
        <Button type="primary" icon={<BulbOutlined />} loading={aiLoading} onClick={() => void runAi()}>
          一键 AI 选股
        </Button>
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
            {ai.personalized_top5 && ai.personalized_top5.length > 0 ? (
              <>
                <Typography.Title level={5} style={{ marginTop: 16 }}>
                  个性化 TOP5（五行 / 流年 + 金融统计，趣味展示）
                </Typography.Title>
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) => String(row.rank)}
                  dataSource={ai.personalized_top5}
                  scroll={{ x: "max-content" }}
                  columns={[
                    { title: "#", dataIndex: "rank", width: 40 },
                    { title: "代码", dataIndex: "code", width: 88 },
                    { title: "名称", dataIndex: "name", ellipsis: true },
                    { title: "赛道", dataIndex: "track", width: 88 },
                    { title: "综合分", dataIndex: "composite_score", width: 88 },
                    {
                      title: "命理/流年结构化",
                      dataIndex: "reason_mingli_structured",
                      ellipsis: true
                    },
                    { title: "金融统计", dataIndex: "reason_finance", ellipsis: true }
                  ]}
                />
              </>
            ) : null}
          </Card>
        )}
      </PageCard>
      <Link to="/fbti-result">查看 FBTI 人格详情</Link>
    </div>
  );
}
