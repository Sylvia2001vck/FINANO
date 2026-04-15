import { Col, List, Row, Statistic, Typography } from "antd";
import { useEffect, useState } from "react";
import { ProfitTrendChart } from "../../components/Chart/ProfitTrendChart";
import { PageCard } from "../../components/UI/PageCard";
import { fetchHotNews, fetchTradeStats, fetchTrades } from "../../services/trade";
import { HotNewsItem, Trade, TradeStats } from "../../types/trade";
import { currency, percent } from "../../utils/format";

export default function DashboardPage() {
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [hotNews, setHotNews] = useState<HotNewsItem[]>([]);

  useEffect(() => {
    void Promise.all([fetchTradeStats(), fetchTrades(), fetchHotNews()]).then(([tradeStats, tradeItems, news]) => {
      setStats(tradeStats);
      setTrades(tradeItems);
      setHotNews(news);
    });
  }, []);

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
        <ProfitTrendChart trades={trades} />
      </PageCard>
      <PageCard title="金融热点">
        <List
          dataSource={hotNews}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta title={item.title} description={`${item.summary} 来源：${item.source}`} />
            </List.Item>
          )}
        />
      </PageCard>
    </div>
  );
}
