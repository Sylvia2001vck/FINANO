import { LikeOutlined } from "@ant-design/icons";
import { Button, Card, Col, Form, Input, List, Row, Select, Space, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { getAgentProfile, saveAgentProfile } from "../../services/agent";
import { getFbtiProfile, type FbtiArchetype } from "../../services/fbti";
import { createPost, fetchPosts, likePost } from "../../services/trade";
import { PostItem } from "../../types/trade";

const MBTI = [
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

const RISK_OPTIONS = [
  { value: 1, label: "1 · 保守型（极低波动偏好）" },
  { value: 2, label: "2 · 稳健型（侧重本金安全）" },
  { value: 3, label: "3 · 均衡型（风险与收益平衡）" },
  { value: 4, label: "4 · 积极型（可承受较大波动）" },
  { value: 5, label: "5 · 进取型（追求高弹性）" }
];

/** 用户档案 + FBTI 画像 + 社区（AI娱乐选基为侧栏独立模块 /ai-fund-pick） */
export default function UserCommunityPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [profileForm] = Form.useForm();
  const [profileLoading, setProfileLoading] = useState(false);

  const [fbtiLoading, setFbtiLoading] = useState(true);
  const [fbtiCode, setFbtiCode] = useState<string | null>(null);
  const [arch, setArch] = useState<FbtiArchetype | null>(null);
  const [fbtiImageMissing, setFbtiImageMissing] = useState(false);

  const [posts, setPosts] = useState<PostItem[]>([]);
  const [postForm] = Form.useForm();

  useEffect(() => {
    const id = location.hash?.replace("#", "");
    if (id) {
      requestAnimationFrame(() => {
        document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [location.hash, location.pathname]);

  useEffect(() => {
    void getAgentProfile()
      .then((res) => {
        const raw = res?.saved_fields as Record<string, unknown> | null | undefined;
        if (raw?.birth_date) {
          profileForm.setFieldsValue({
            user_birth: raw.birth_date,
            user_mbti: raw.mbti,
            risk_preference: raw.risk_preference ?? undefined
          });
        }
      })
      .catch(() => {});
  }, [profileForm]);

  useEffect(() => {
    void getFbtiProfile()
      .then((d) => {
        setFbtiCode(d.fbti_profile);
        setArch(d.archetype);
      })
      .catch(() => message.warning("读取 FBTI 失败"))
      .finally(() => setFbtiLoading(false));
  }, []);

  useEffect(() => {
    setFbtiImageMissing(false);
  }, [fbtiCode]);

  const loadPosts = async () => {
    const p = await fetchPosts();
    setPosts(p);
  };

  useEffect(() => {
    void loadPosts();
  }, []);

  return (
    <div className="page-stack">
      <Typography.Title level={3}>用户与社区</Typography.Title>
      <Typography.Paragraph type="secondary">
        <strong>用户档案</strong>（MAFB 用画像）→ <strong>FBTI 金融人格</strong> → <strong>社区</strong>。
        趣味向选基请使用侧栏「<Link to="/ai-fund-pick">AI娱乐选基</Link>」独立入口。
      </Typography.Paragraph>

      <section id="profile" style={{ scrollMarginTop: 16 }}>
        <Typography.Title level={4}>用户档案</Typography.Title>
        <Typography.Paragraph type="secondary">
          保存 MBTI、生日与风险偏好，供多智能体基金推荐使用；命理特征均为结构化规则输出。
        </Typography.Paragraph>
        <PageCard title="编辑并保存">
          <Form
            form={profileForm}
            layout="vertical"
            onFinish={async (values) => {
              setProfileLoading(true);
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
                setProfileLoading(false);
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
            <Button type="primary" htmlType="submit" loading={profileLoading}>
              保存画像
            </Button>
          </Form>
        </PageCard>
      </section>

      <section id="fbti" style={{ marginTop: 32, scrollMarginTop: 16 }}>
        <Typography.Title level={4}>FBTI 画像</Typography.Title>
        {fbtiLoading ? (
          <Typography.Paragraph>加载中…</Typography.Paragraph>
        ) : !fbtiCode ? (
          <PageCard title="尚未完成 FBTI">
            <Typography.Paragraph>请先完成测试。</Typography.Paragraph>
            <Link to="/fbti-test">
              <Button type="primary">去测试</Button>
            </Link>
          </PageCard>
        ) : (
          <>
            <Space style={{ marginBottom: 12 }} wrap>
              <Button onClick={() => navigate("/fbti-test?retake=1")}>重新测试</Button>
            </Space>
            <Card>
              <Row gutter={[20, 16]} align="middle">
                <Col xs={24} md={16}>
                  <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <div>
                      <Typography.Text type="secondary">代码 </Typography.Text>
                      <Typography.Text code style={{ fontSize: 22 }}>
                        {fbtiCode}
                      </Typography.Text>
                    </div>
                    {arch && (
                      <>
                        <Typography.Title level={5} style={{ margin: 0 }}>
                          {arch.name}
                          {arch.nearest_archetype ? (
                            <Typography.Text type="secondary">（最近归档）</Typography.Text>
                          ) : null}
                        </Typography.Title>
                        <Typography.Paragraph>{arch.description || arch.blurb}</Typography.Paragraph>
                        {arch.risk_level ? (
                          <Typography.Text type="secondary">风险档位（演示）：{arch.risk_level}</Typography.Text>
                        ) : null}
                        {arch.fund_preference ? (
                          <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                            选股偏好：{arch.fund_preference}
                          </Typography.Paragraph>
                        ) : null}
                        <Space wrap>
                          {(arch.tags || arch.style_tags || []).map((t) => (
                            <Tag key={t}>{t}</Tag>
                          ))}
                        </Space>
                      </>
                    )}
                  </Space>
                </Col>
                <Col xs={24} md={8}>
                  {!fbtiImageMissing && fbtiCode ? (
                    <img
                      src={`/fbti/${String(fbtiCode).toUpperCase()}.png`}
                      alt={`${fbtiCode} 人格形象`}
                      onError={() => setFbtiImageMissing(true)}
                      style={{
                        width: "100%",
                        maxWidth: 240,
                        height: "auto",
                        maxHeight: 260,
                        objectFit: "contain",
                        display: "block",
                        margin: "0 auto"
                      }}
                    />
                  ) : (
                    <Typography.Text type="secondary">未找到对应形象图（请检查 asset 文件名）。</Typography.Text>
                  )}
                </Col>
              </Row>
            </Card>
          </>
        )}
      </section>

      <section id="community" style={{ marginTop: 32, scrollMarginTop: 16 }}>
        <Typography.Title level={4}>社区</Typography.Title>
        <PageCard title="发布帖子">
          <Form
            form={postForm}
            layout="vertical"
            onFinish={async (values) => {
              await createPost(values);
              message.success("发布成功");
              postForm.resetFields();
              await loadPosts();
            }}
          >
            <Form.Item label="标题" name="title" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item label="内容" name="content" rules={[{ required: true }]}>
              <Input.TextArea rows={4} />
            </Form.Item>
            <Button type="primary" htmlType="submit">
              发布
            </Button>
          </Form>
        </PageCard>
        <PageCard title="社区动态（发帖 + 点赞）" style={{ marginTop: 16 }}>
          <List
            dataSource={posts}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="like"
                    type="link"
                    icon={<LikeOutlined />}
                    onClick={async () => {
                      await likePost(item.id);
                      await loadPosts();
                    }}
                  >
                    {item.likes}
                  </Button>
                ]}
              >
                <List.Item.Meta title={item.title} description={item.content} />
              </List.Item>
            )}
          />
        </PageCard>
      </section>
    </div>
  );
}
