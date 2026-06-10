import { Col, List, Row, Space, Statistic, Typography } from "antd";
import { useEffect, useState } from "react";
import { ProfitTrendChart } from "../../components/Chart/ProfitTrendChart";
import { PageCard } from "../../components/UI/PageCard";
import { useT } from "../../hooks/useT";
import { fetchHotNews, fetchTradeStats } from "../../services/trade";
import { HotNewsItem, TradeStats } from "../../types/trade";
import { currency, percent } from "../../utils/format";

export default function DashboardPage() {
  const { t } = useT();
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
      <Typography.Title level={3}>{t("dashboard.title")}</Typography.Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title={t("dashboard.totalTrades")} value={stats?.total_trades || 0} /></PageCard>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title={t("dashboard.winRate")} value={percent(stats?.win_rate || 0)} /></PageCard>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title={t("dashboard.totalProfit")} value={currency(stats?.total_profit || 0)} /></PageCard>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <PageCard><Statistic title={t("dashboard.profitFactor")} value={stats?.profit_factor || 0} precision={2} /></PageCard>
        </Col>
      </Row>
      <PageCard title={t("dashboard.profitCurve")}>
        <ProfitTrendChart dailyPnlSeries={stats?.daily_pnl_series || []} />
      </PageCard>
      <PageCard
        title={
          <Space style={{ width: "100%", justifyContent: "space-between" }}>
            <span>{t("dashboard.hotNews")}</span>
            {hotUpdatedText ? (
              <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                {t("common.updatedAt")} {hotUpdatedText}
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
              <List.Item.Meta
                title={`${item.rank}. ${item.title}`}
                description={`${item.summary} ${t("common.source")}：${item.source}`}
              />
            </List.Item>
          )}
        />
      </PageCard>
    </div>
  );
}
