import { Button, Form, Input, Select, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { getAgentProfile, saveAgentProfile } from "../../services/agent";

const MBTI = ["INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP", "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"].map((v) => ({
  value: v,
  label: v
}));

/** 与后端 risk_preference 1–5 一致，仅存数字，界面用中文描述 */
const RISK_OPTIONS = [
  { value: 1, label: "1 · 保守型（极低波动偏好）" },
  { value: 2, label: "2 · 稳健型（侧重本金安全）" },
  { value: 3, label: "3 · 均衡型（风险与收益平衡）" },
  { value: 4, label: "4 · 积极型（可承受较大波动）" },
  { value: 5, label: "5 · 进取型（追求高弹性）" }
];

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
            risk_preference: raw.risk_preference ?? undefined
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
        保存 MBTI、生日与风险偏好，供多智能体基金推荐使用；命理特征均为结构化规则输出。
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
                risk_preference: values.risk_preference ?? undefined
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
          <Form.Item label="风险偏好" name="risk_preference" tooltip="对应 MAFB 内风险等级融合权重">
            <Select allowClear placeholder="请选择" options={RISK_OPTIONS} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            保存画像
          </Button>
        </Form>
      </PageCard>
    </div>
  );
}
