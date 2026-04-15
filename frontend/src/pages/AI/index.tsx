import { Button, Card, Empty, List, Select, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { analyzeTrade, fetchTrades } from "../../services/trade";
import { AiAnalysisResult, Trade } from "../../types/trade";

export default function AIPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [selectedTradeId, setSelectedTradeId] = useState<number>();
  const [result, setResult] = useState<AiAnalysisResult | null>(null);

  useEffect(() => {
    void fetchTrades().then(setTrades);
  }, []);

  return (
    <div className="page-stack">
      <PageCard title="AI 交易分析">
        <Space direction="vertical" style={{ width: "100%" }}>
          <Select
            placeholder="选择一笔交易"
            options={trades.map((item) => ({
              value: item.id,
              label: `${item.trade_date} ${item.symbol} ${item.name} ${item.profit}`
            }))}
            value={selectedTradeId}
            onChange={setSelectedTradeId}
          />
          <Button
            type="primary"
            disabled={!selectedTradeId}
            onClick={async () => {
              if (!selectedTradeId) return;
              setResult(await analyzeTrade(selectedTradeId));
            }}
          >
            生成分析
          </Button>
        </Space>
      </PageCard>
      {result ? (
        <Card>
          <Typography.Title level={5}>优点</Typography.Title>
          <List dataSource={result.strengths} renderItem={(item) => <List.Item>{item}</List.Item>} />
          <Typography.Title level={5}>问题</Typography.Title>
          <List dataSource={result.problems} renderItem={(item) => <List.Item>{item}</List.Item>} />
          <Typography.Title level={5}>建议</Typography.Title>
          <List dataSource={result.suggestions} renderItem={(item) => <List.Item>{item}</List.Item>} />
        </Card>
      ) : (
        <Empty description="选择交易后生成 AI 分析" />
      )}
    </div>
  );
}
