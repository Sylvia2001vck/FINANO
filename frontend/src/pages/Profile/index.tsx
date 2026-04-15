import { UploadOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, InputNumber, Select, Space, Typography, Upload, message } from "antd";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { getAgentProfile, ocrBirth, saveAgentProfile } from "../../services/agent";

const MBTI = ["INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP", "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"].map((v) => ({
  value: v,
  label: v
}));

export default function ProfilePage() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void getAgentProfile()
      .then((res) => {
        const raw = res?.saved_fields as Record<string, unknown> | null | undefined;
        if (raw?.birth_date) {
          form.setFieldsValue({
            user_birth: raw.birth_date,
            user_mbti: raw.mbti,
            layout_facing: raw.layout_facing,
            risk_preference: raw.risk_preference
          });
        }
      })
      .catch(() => {
        /* 未登录或未保存 */
      });
  }, [form]);

  return (
    <div className="page-stack">
      <Typography.Title level={3}>个人画像（MAFB）</Typography.Title>
      <Typography.Paragraph type="secondary">
        保存 MBTI、生日、环境偏好与风险偏好，供多智能体基金推荐使用；命理特征均为结构化规则输出，用于课程演示。
      </Typography.Paragraph>
      <PageCard title="编辑并保存">
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            setLoading(true);
            try {
              await saveAgentProfile({
                user_birth: values.user_birth,
                user_mbti: values.user_mbti,
                layout_facing: values.layout_facing,
                risk_preference: values.risk_preference
              });
              message.success("画像已保存");
            } catch (e) {
              message.error(e instanceof Error ? e.message : "保存失败");
            } finally {
              setLoading(false);
            }
          }}
        >
          <Form.Item label="出生日期" name="user_birth" rules={[{ required: true }]}>
            <Input placeholder="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item label="MBTI" name="user_mbti" rules={[{ required: true }]}>
            <Select options={MBTI} showSearch />
          </Form.Item>
          <Form.Item label="环境偏好 N/S/E/W" name="layout_facing">
            <Select allowClear options={["N", "S", "E", "W"].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item label="风险偏好 1-5（可选）" name="risk_preference">
            <InputNumber min={1} max={5} style={{ width: "100%" }} />
          </Form.Item>
          <Space wrap>
            <Button type="primary" htmlType="submit" loading={loading}>
              保存画像
            </Button>
            <Upload
              showUploadList={false}
              beforeUpload={async (file) => {
                try {
                  const data = await ocrBirth(file);
                  if (data.user_birth) form.setFieldsValue({ user_birth: data.user_birth });
                  message.info(data.hint);
                } catch (e) {
                  message.error(e instanceof Error ? e.message : "OCR 失败");
                }
                return false;
              }}
            >
              <Button icon={<UploadOutlined />}>OCR 识别生日</Button>
            </Upload>
          </Space>
        </Form>
      </PageCard>
    </div>
  );
}
