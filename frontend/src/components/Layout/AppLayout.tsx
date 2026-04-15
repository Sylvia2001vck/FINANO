import {
  BarChartOutlined,
  BulbOutlined,
  ClusterOutlined,
  FileTextOutlined,
  LineChartOutlined,
  LoginOutlined,
  ScanOutlined,
  TeamOutlined,
  UserOutlined,
  ExperimentOutlined
} from "@ant-design/icons";
import { Layout, Menu, Typography, Button, Space } from "antd";
import { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useUserStore } from "../../store/userStore";

const { Header, Sider, Content } = Layout;

interface Props {
  children: ReactNode;
}

export function AppLayout({ children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser, logout } = useUserStore();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider breakpoint="lg" collapsedWidth="0">
        <div style={{ color: "#fff", padding: 20, fontSize: 20, fontWeight: 700 }}>Finano</div>
        <Menu
          theme="dark"
          selectedKeys={[location.pathname]}
          items={[
            { key: "/", icon: <BarChartOutlined />, label: "仪表盘" },
            { key: "/trade", icon: <FileTextOutlined />, label: "交易记录" },
            { key: "/note", icon: <FileTextOutlined />, label: "投资笔记" },
            { key: "/ai", icon: <BulbOutlined />, label: "AI 分析" },
            { key: "/ocr-fund", icon: <ScanOutlined />, label: "OCR 识图" },
            { key: "/similar-funds", icon: <LineChartOutlined />, label: "相似基金" },
            { key: "/mafb", icon: <ClusterOutlined />, label: "多智能体控制台" },
            { key: "/fbti-test", icon: <ExperimentOutlined />, label: "FBTI 测试" },
            { key: "/fbti-result", icon: <ExperimentOutlined />, label: "FBTI 结果" },
            { key: "/profile", icon: <UserOutlined />, label: "用户档案" },
            { key: "/community", icon: <TeamOutlined />, label: "社区" }
          ]}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between"
          }}
        >
          <Typography.Title level={4} style={{ margin: 0 }}>
            Finano 课程项目演示版
          </Typography.Title>
          <Space>
            <Typography.Text>{currentUser?.username}</Typography.Text>
            <Button icon={<LoginOutlined />} onClick={() => { logout(); navigate("/login"); }}>
              退出登录
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: 24 }}>
          {children}
        </Content>
      </Layout>
    </Layout>
  );
}
