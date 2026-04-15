import { UploadOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Form,
  Input,
  List,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { listAgentFunds, ocrBirth, runMafb } from "../../services/agent";

const MBTI_OPTIONS = [
  "INTJ",
  "INTP",
  "ENTJ",
  "ENTP",
  "INFJ",
  "INFP",
  "ENFJ",
  "ENFP",
  "ISTJ",
  "ISFJ",
  "ESTJ",
  "ESFJ",
  "ISTP",
  "ISFP",
  "ESTP",
  "ESFP"
].map((v) => ({ value: v, label: v }));

export default function MAFBPage() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [funds, setFunds] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void listAgentFunds()
      .then(setFunds)
      .catch(() => {
        /* ignore */
      });
  }, []);

  const onRun = async (values: {
    user_birth?: string;
    user_mbti?: string;
    fund_code: string;
    layout_facing?: string;
    use_saved_profile?: boolean;
  }) => {
    if (!values.use_saved_profile && (!values.user_birth || !values.user_mbti)) {
      message.warning("请填写生日与 MBTI，或在「个人画像」页保存后勾选使用已保存画像");
      return;
    }
    setLoading(true);
    try {
      const data = await runMafb({
        fund_code: values.fund_code,
        user_birth: values.use_saved_profile ? undefined : values.user_birth,
        user_mbti: values.use_saved_profile ? undefined : values.user_mbti,
        layout_facing: values.layout_facing || undefined,
        use_saved_profile: Boolean(values.use_saved_profile)
      });
      setReport(data.final_report as Record<string, unknown>);
      message.success("MAFB 流水线执行完成");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "执行失败");
    } finally {
      setLoading(false);
    }
  };

  const scores = (report?.scores as Record<string, number> | undefined) || {};
  const portfolio = (report?.proposed_portfolio as Record<string, unknown>[] | undefined) || [];
  const top5 = (report?.top5_recommendations as Record<string, unknown>[] | undefined) || [];
  const chain = (report?.reasoning_chain as string[] | undefined) || [];
  const position = report?.position_advice as Record<string, unknown> | undefined;
  const verdict = report?.verdict as string | undefined;

  return (
    <div className="page-stack">
      <Typography.Title level={3}>MAFB 多智能体控制台</Typography.Title>
      <Typography.Paragraph type="secondary">
        LangGraph 0.2.x 状态共享 + User Profiling / Fundamental / Technical / Risk / Compliance / Allocation
        六类节点；云端 DashScope 金融模型优先，本地 Qwen-1.8B CPU 兜底；FAISS 向量检索。输出强制 JSON，仅供演示。
      </Typography.Paragraph>

      <PageCard title="输入与运行">
        <Form
          form={form}
          layout="vertical"
          onFinish={onRun}
          initialValues={{
            user_birth: "1998-06-01",
            user_mbti: "INTJ",
            fund_code: "510300",
            layout_facing: "N",
            use_saved_profile: false
          }}
        >
          <Form.Item name="use_saved_profile" valuePropName="checked">
            <Checkbox>使用已在「个人画像」中保存的 MBTI 与生日（千人千面）</Checkbox>
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="出生日期" name="user_birth">
                <Input placeholder="YYYY-MM-DD" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="MBTI" name="user_mbti">
                <Select options={MBTI_OPTIONS} showSearch />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="基金 / ETF 代码" name="fund_code" rules={[{ required: true }]}>
                <Input placeholder="如 510300" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="环境偏好 N/S/E/W（可选）" name="layout_facing">
                <Select allowClear options={[{ value: "N", label: "N" }, { value: "S", label: "S" }, { value: "E", label: "E" }, { value: "W", label: "W" }]} />
              </Form.Item>
            </Col>
          </Row>
          <Space wrap>
            <Button type="primary" htmlType="submit" loading={loading}>
              运行 MAFB 流水线
            </Button>
            <Upload
              showUploadList={false}
              beforeUpload={async (file) => {
                try {
                  const data = await ocrBirth(file);
                  if (data.user_birth) {
                    form.setFieldsValue({ user_birth: data.user_birth });
                  }
                  message.info(data.hint);
                } catch (error) {
                  message.error(error instanceof Error ? error.message : "OCR 失败");
                }
                return false;
              }}
            >
              <Button icon={<UploadOutlined />}>OCR 识别生日</Button>
            </Upload>
          </Space>
        </Form>
      </PageCard>

      <PageCard title="演示基金池">
        <Table
          size="small"
          rowKey="code"
          pagination={{ pageSize: 6 }}
          dataSource={funds}
          columns={[
            { title: "代码", dataIndex: "code" },
            { title: "名称", dataIndex: "name" },
            { title: "赛道", dataIndex: "track" },
            { title: "风险等级", dataIndex: "risk_rating" }
          ]}
        />
      </PageCard>

      {report && (
        <PageCard title="结构化输出">
          <Space direction="vertical" style={{ width: "100%" }} size="large">
            <div>
              <Tag color={verdict === "pass" ? "green" : "red"}>{verdict === "pass" ? "合规通过" : "合规拦截"}</Tag>
              <Typography.Text> 加权总分：{String(report.weighted_total ?? "-")}</Typography.Text>
            </div>
            <Typography.Title level={5}>各智能体打分</Typography.Title>
            <Descriptions bordered size="small" column={2}>
              {Object.entries(scores).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {v}
                </Descriptions.Item>
              ))}
            </Descriptions>
            <Typography.Title level={5}>个性化 TOP5（命理结构化 + 金融统计双理由）</Typography.Title>
            <Table
              size="small"
              rowKey={(row) => String(row.rank)}
              dataSource={top5}
              pagination={false}
              columns={[
                { title: "#", dataIndex: "rank", width: 48 },
                { title: "代码", dataIndex: "code" },
                { title: "名称", dataIndex: "name" },
                { title: "赛道", dataIndex: "track" },
                { title: "综合分", dataIndex: "composite_score" },
                {
                  title: "命理/结构化理由",
                  dataIndex: "reason_mingli_structured",
                  ellipsis: true
                },
                { title: "金融理由", dataIndex: "reason_finance", ellipsis: true }
              ]}
            />
            <Typography.Title level={5}>仓位与风险建议</Typography.Title>
            <Card size="small">
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify(position ?? {}, null, 2)}
              </pre>
            </Card>
            <Typography.Title level={5}>可解释推理链</Typography.Title>
            <List size="small" bordered dataSource={chain} renderItem={(item) => <List.Item>{item}</List.Item>} />
            <Typography.Title level={5}>组合草案</Typography.Title>
            <Table
              size="small"
              rowKey={(row) => String(row.code)}
              dataSource={portfolio}
              columns={[
                { title: "代码", dataIndex: "code" },
                { title: "名称", dataIndex: "name" },
                { title: "角色", dataIndex: "role" },
                { title: "权重", dataIndex: "weight" },
                { title: "说明", dataIndex: "rationale" }
              ]}
            />
            <Typography.Title level={5}>摘要与投教声明</Typography.Title>
            <Card size="small">
              <Typography.Paragraph>{String(report.summary ?? "")}</Typography.Paragraph>
              <Typography.Text type="secondary">{String(report.disclaimer ?? "")}</Typography.Text>
            </Card>
          </Space>
        </PageCard>
      )}
    </div>
  );
}
