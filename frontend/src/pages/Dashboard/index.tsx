import { Col, List, Row, Space, Statistic, Typography } from "antd";
import { useEffect, useState } from "react";
import { ProfitTrendChart } from "../../components/Chart/ProfitTrendChart";
import { PageCard } from "../../components/UI/PageCard";
import { fetchHotNews, fetchTradeStats } from "../../services/trade";
import { HotNewsItem, TradeStats } from "../../types/trade";
import { currency, percent } from "../../utils/format";

export default function DashboardPage() {
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [hotNews, setHotNews] = useState<HotNewsItem[]>([]);
  const [hotUpdatedAt, setHotUpdatedAt] = useState<string>("");

  useEffect(() => {
    void Promise.all([fetchTradeStats(), fetchHotNews()]).then(([tradeStats, news]) => {
      setStats(tradeStats);
      setHotNews(news.items || []);
      setHotUpdatedAt(news.updated_at || "");
    });
  }, []);

  const hotUpdatedText = hotUpdatedAt ? hotUpdatedAt.slice(0, 16).replace("T", " ") : "";

  return (
    <div className="page-stack">
      <Typography.Title level={3}>仪表盘</Typography.Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title="总交易数" value={stats?.total_trades || 0} /></PageCard>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title="胜率" value={percent(stats?.win_rate || 0)} /></PageCard>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title="累计收益" value={currency(stats?.total_profit || 0)} /></PageCard>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title="盈亏因子" value={stats?.profit_factor || 0} precision={2} /></PageCard>
        </Col>
      </Row>
      <PageCard title="收益曲线">
        <ProfitTrendChart dailyPnlSeries={stats?.daily_pnl_series || []} />
      </PageCard>
      <PageCard
        title={
          <Space style={{ width: "100%", justifyContent: "space-between" }}>
            <span>金融热点</span>
            {hotUpdatedText ? (
              <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                更新于 {hotUpdatedText}
              </Typography.Text>
            ) : null}
          </Space>
        }
      >
        <List
          dataSource={hotNews}
          pagination={{
            pageSize: 3,
            hideOnSinglePage: true,
            showSizeChanger: false,
            size: "small",
          }}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta title={`${item.rank}. ${item.title}`} description={`${item.summary} 来源：${item.source}`} />
            </List.Item>
          )}
        />
      </PageCard>
    </div>
  );
}
