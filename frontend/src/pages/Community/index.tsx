import { Button, Form, Input, List, message } from "antd";
import { LikeOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { PostItem } from "../../types/trade";
import { createPost, fetchPosts, likePost } from "../../services/trade";

export default function CommunityPage() {
  const [posts, setPosts] = useState<PostItem[]>([]);
  const [form] = Form.useForm();

  const load = async () => {
    const p = await fetchPosts();
    setPosts(p);
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="page-stack">
      <PageCard title="发布帖子">
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            await createPost(values);
            message.success("发布成功");
            form.resetFields();
            await load();
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
      <PageCard title="社区动态（发帖 + 点赞）">
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
                    await load();
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
    </div>
  );
}
