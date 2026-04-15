import { Button, Form, Input, List, message } from "antd";
import { useEffect, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import { createNote, fetchNotes } from "../../services/trade";
import { NoteItem } from "../../types/trade";

export default function NotePage() {
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [form] = Form.useForm();

  const load = async () => {
    setNotes(await fetchNotes());
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="page-stack">
      <PageCard title="新增复盘笔记">
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            await createNote(values);
            message.success("笔记已保存");
            form.resetFields();
            await load();
          }}
        >
          <Form.Item label="标题" name="title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="关联交易ID" name="trade_id">
            <Input />
          </Form.Item>
          <Form.Item label="标签" name="tags">
            <Input placeholder="趋势,仓位,止损" />
          </Form.Item>
          <Form.Item label="内容" name="content" rules={[{ required: true }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
          <Button type="primary" htmlType="submit">保存笔记</Button>
        </Form>
      </PageCard>
      <PageCard title="我的复盘笔记">
        <List
          dataSource={notes}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta title={item.title} description={`${item.content} ${item.tags ? `#${item.tags}` : ""}`} />
            </List.Item>
          )}
        />
      </PageCard>
    </div>
  );
}
