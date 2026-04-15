import { Button, Form, Input, InputNumber, Modal, Select, Space, Table, Upload, message } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { createTrade, fetchTradeStats, fetchTrades, importTradeByOcr } from "../../services/trade";
import { Trade, TradeStats } from "../../types/trade";
import { currency } from "../../utils/format";

export default function TradePage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    const [tradeData, summary] = await Promise.all([fetchTrades(), fetchTradeStats()]);
    setTrades(tradeData);
    setStats(summary);
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="page-stack">
      <Space className="page-actions">
        <Button type="primary" onClick={() => setOpen(true)}>新增交易</Button>
        <Upload
          showUploadList={false}
          beforeUpload={async (file) => {
            await importTradeByOcr(file);
            message.success("OCR 导入成功");
            await load();
            return false;
          }}
        >
          <Button icon={<UploadOutlined />}>导入交割单</Button>
        </Upload>
      </Space>
      <PageCard title={`交易记录（累计收益 ${currency(stats?.total_profit || 0)}）`}>
        <Table
          rowKey="id"
          dataSource={trades}
          pagination={{ pageSize: 8 }}
          columns={[
            { title: "日期", dataIndex: "trade_date" },
            { title: "代码", dataIndex: "symbol" },
            { title: "名称", dataIndex: "name" },
            { title: "方向", dataIndex: "direction" },
            { title: "成交额", dataIndex: "amount", render: (value: number) => currency(value) },
            { title: "盈亏", dataIndex: "profit", render: (value: number) => currency(value) },
            { title: "平台", dataIndex: "platform" }
          ]}
        />
      </PageCard>
      <Modal
        title="新增交易"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            await createTrade(values);
            message.success("交易创建成功");
            setOpen(false);
            form.resetFields();
            await load();
          }}
        >
          <Form.Item label="交易日期" name="trade_date" rules={[{ required: true }]}>
            <Input placeholder="2024-01-05" />
          </Form.Item>
          <Form.Item label="证券代码" name="symbol" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="证券名称" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="方向" name="direction" initialValue="buy" rules={[{ required: true }]}>
            <Select options={[{ value: "buy", label: "买入" }, { value: "sell", label: "卖出" }]} />
          </Form.Item>
          <Form.Item label="数量" name="quantity" rules={[{ required: true }]}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="价格" name="price" rules={[{ required: true }]}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="成交额" name="amount" rules={[{ required: true }]}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="手续费" name="fee" initialValue={0}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="盈亏" name="profit" initialValue={0}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="平台" name="platform" initialValue="manual">
            <Input />
          </Form.Item>
          <Form.Item label="备注" name="notes">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
