import { SearchOutlined } from "@ant-design/icons";
import { Button, Form, Input, Table, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { SimilarFundRow, fetchSimilarFunds } from "../../services/agent";

export default function SimilarFundsPage() {
  const [params] = useSearchParams();
  const urlCode = (params.get("code") || "").trim();
  const [form] = Form.useForm();
  const [rows, setRows] = useState<SimilarFundRow[]>([]);
  const [refCode, setRefCode] = useState("");

  const run = useCallback(async (code: string) => {
    const c = code.trim();
    if (!/^\d{6}$/.test(c)) {
      message.warning("请输入 6 位数字基金代码");
      return;
    }
    try {
      const data = await fetchSimilarFunds(c);
      setRefCode(data.reference_code);
      setRows(data.similar || []);
      if (!data.similar?.length) {
        message.info("演示池内未找到该基金或无可比标的");
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "查询失败");
    }
  }, []);

  useEffect(() => {
    if (!urlCode || !/^\d{6}$/.test(urlCode)) {
      return;
    }
    form.setFieldsValue({ code: urlCode });
    void run(urlCode);
  }, [urlCode, form, run]);

  return (
    <div className="page-stack">
      <Typography.Title level={3}>相似基金对比</Typography.Title>
      <Typography.Paragraph type="secondary">
        基于演示基金池的多维特征（夏普、动量、回撤、风险等级、规模）做 Pandas 归一化与余弦相似度排序，企业轻量演示用，非全市场行情拟合。
      </Typography.Paragraph>

      <PageCard title="查询">
        <Form
          form={form}
          layout="inline"
          onFinish={(v) => void run(v.code)}
          initialValues={{ code: urlCode || "510300" }}
        >
          <Form.Item name="code" rules={[{ required: true, message: "请输入代码" }]}>
            <Input placeholder="6 位代码" maxLength={6} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              计算相似度
            </Button>
          </Form.Item>
        </Form>
      </PageCard>

      {refCode ? (
        <PageCard title={`与 ${refCode} 最接近的标的（演示池）`}>
          <Table
            rowKey="code"
            size="small"
            pagination={false}
            dataSource={rows}
            columns={[
              { title: "代码", dataIndex: "code", width: 100 },
              { title: "名称", dataIndex: "name" },
              { title: "赛道", dataIndex: "track", width: 100 },
              { title: "相似度", dataIndex: "similarity", width: 100 },
              { title: "说明", dataIndex: "rationale", ellipsis: true }
            ]}
          />
        </PageCard>
      ) : null}
    </div>
  );
}
