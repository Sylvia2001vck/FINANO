import { LinkOutlined, UploadOutlined } from "@ant-design/icons";
import { Button, List, Space, Tag, Typography, Upload, message } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { ocrFundCode } from "../../services/agent";

export default function OcrFundPage() {
  const [codes, setCodes] = useState<string[]>([]);
  const [primary, setPrimary] = useState<string | null>(null);
  const [hint, setHint] = useState<string>("");

  return (
    <div className="page-stack">
      <Typography.Title level={3}>OCR · 基金代码识图</Typography.Title>
      <Typography.Paragraph type="secondary">
        上传含 6 位基金或 ETF 代码的截图，服务端使用 EasyOCR 抽取代码（金融演示场景，不解析交割单）。
        未安装 EasyOCR 时接口会返回安装提示，不影响其余功能。
      </Typography.Paragraph>

      <PageCard title="上传图片">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Upload
            accept="image/*"
            showUploadList={false}
            beforeUpload={async (file) => {
              try {
                const data = await ocrFundCode(file);
                setCodes(data.codes || []);
                setPrimary(data.primary_code ?? (data.codes && data.codes[0] ? data.codes[0] : null));
                setHint(data.hint || "");
                if (data.codes?.length) {
                  message.success("识别完成");
                } else {
                  message.info(data.hint || "未识别到代码");
                }
              } catch (e) {
                message.error(e instanceof Error ? e.message : "识别失败");
              }
              return false;
            }}
          >
            <Button type="primary" icon={<UploadOutlined />}>
              选择图片并识别
            </Button>
          </Upload>
          {hint ? <Typography.Text type="secondary">{hint}</Typography.Text> : null}
          {primary ? (
            <div>
              <Typography.Text>主候选：</Typography.Text>{" "}
              <Tag color="blue" style={{ fontSize: 15 }}>
                {primary}
              </Tag>
            </div>
          ) : null}
        </Space>
      </PageCard>

      {codes.length > 0 && (
        <PageCard title="候选代码">
          <List
            bordered
            dataSource={codes}
            renderItem={(code) => (
              <List.Item
                actions={[
                  <Link key="sim" to={`/similar-funds?code=${encodeURIComponent(code)}`}>
                    查相似基金 <LinkOutlined />
                  </Link>,
                  <Link key="mafb" to="/mafb">
                    去 MAFB 控制台
                  </Link>
                ]}
              >
                <Typography.Text code style={{ fontSize: 16 }}>
                  {code}
                </Typography.Text>
              </List.Item>
            )}
          />
        </PageCard>
      )}
    </div>
  );
}
