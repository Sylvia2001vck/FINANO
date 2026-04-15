import {
  BarChartOutlined,
  BulbOutlined,
  ClusterOutlined,
  FileTextOutlined,
  LoginOutlined,
  TeamOutlined,
  UserOutlined,
  ExperimentOutlined,
  ThunderboltOutlined
} from "@ant-design/icons";
import { ConfigProvider, Layout, Menu, Typography, Button, Space } from "antd";
import { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { FinanoLogo } from "../FinanoLogo";
import { useUserStore } from "../../store/userStore";

const { Header, Sider, Content } = Layout;

/** 与商标黑底/灰阶主色一致 */
const shell = {
  siderBg: "#080808",
  siderHairline: "rgba(255,255,255,0.07)",
  headerBg: "#c8c8c8",
  headerText: "#141414",
  menuSelected: "#252525",
  menuHover: "#141414",
  primaryBtn: "#2a2a2a"
} as const;

interface Props {
  children: ReactNode;
}

export function AppLayout({ children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser, logout } = useUserStore();

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: shell.primaryBtn,
          colorLink: shell.primaryBtn
        },
        components: {
          Layout: {
            siderBg: shell.siderBg,
            headerBg: shell.headerBg,
            bodyBg: "#f2f2f2"
          },
          Menu: {
            darkItemBg: shell.siderBg,
            darkSubMenuItemBg: shell.siderBg,
            darkItemSelectedBg: shell.menuSelected,
            darkItemHoverBg: shell.menuHover,
            darkPopupBg: "#121212",
            darkItemColor: "rgba(255,255,255,0.78)",
            darkItemSelectedColor: "#ffffff",
            colorSplit: shell.siderHairline
          },
          Button: {
            primaryShadow: "none"
          }
        }
      }}
    >
      <Layout style={{ minHeight: "100vh" }}>
        <Sider
          breakpoint="lg"
          collapsedWidth="0"
          width={228}
          style={{ background: shell.siderBg, borderRight: `1px solid ${shell.siderHairline}` }}
        >
          <div
            style={{
              padding: "22px 14px 26px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderBottom: `1px solid ${shell.siderHairline}`
            }}
          >
            <Link to="/" style={{ lineHeight: 0 }} aria-label="FINANO 首页">
              <FinanoLogo variant="mark" height={58} />
            </Link>
          </div>
          <Menu
            theme="dark"
            style={{ background: "transparent", borderInlineEnd: "none" }}
            selectedKeys={[
              ["/fbti-test", "/fbti-result"].includes(location.pathname) ? "/fbti-result" : location.pathname
            ]}
            items={[
              { key: "/", icon: <BarChartOutlined />, label: "仪表盘" },
              { key: "/trade", icon: <FileTextOutlined />, label: "交易记录" },
              { key: "/note", icon: <FileTextOutlined />, label: "投资笔记" },
              { key: "/ai", icon: <BulbOutlined />, label: "AI 分析" },
              { key: "/mafb", icon: <ClusterOutlined />, label: "多智能体控制台" },
              { key: "/fbti-result", icon: <ExperimentOutlined />, label: "FBTI 画像" },
              { key: "/ai-fund-pick", icon: <ThunderboltOutlined />, label: "AI 选股" },
              { key: "/profile", icon: <UserOutlined />, label: "用户档案" },
              { key: "/community", icon: <TeamOutlined />, label: "社区" }
            ]}
            onClick={({ key }) => navigate(key)}
          />
        </Sider>
        <Layout>
          <Header
            style={{
              background: shell.headerBg,
              padding: "0 24px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              borderBottom: "1px solid rgba(0,0,0,0.08)",
              boxShadow: "0 1px 0 rgba(255,255,255,0.35) inset"
            }}
          >
            <Link to="/" style={{ lineHeight: 0, display: "flex", alignItems: "center" }} aria-label="FINANO 首页">
              <FinanoLogo variant="wordmark" height={36} />
            </Link>
            <Space>
              <Typography.Text style={{ color: shell.headerText, fontWeight: 500 }}>
                {currentUser?.username}
              </Typography.Text>
              <Button
                type="primary"
                icon={<LoginOutlined />}
                onClick={() => {
                  logout();
                  navigate("/login");
                }}
              >
                退出登录
              </Button>
            </Space>
          </Header>
          <Content style={{ padding: 24, background: "#f2f2f2" }}>{children}</Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
