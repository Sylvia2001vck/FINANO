from pathlib import Path
from textwrap import dedent


root = Path(r"d:\FINANO\frontend")
files = {
    "package.json": dedent(
        """
        {
          "name": "finano-frontend",
          "private": true,
          "version": "1.0.0",
          "type": "module",
          "scripts": {
            "dev": "vite",
            "build": "tsc && vite build",
            "preview": "vite preview"
          },
          "dependencies": {
            "antd": "^5.15.3",
            "axios": "^1.6.8",
            "dayjs": "^1.11.10",
            "echarts": "^5.5.0",
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
            "react-router-dom": "^6.22.3",
            "zustand": "^4.5.2"
          },
          "devDependencies": {
            "@types/react": "^18.2.67",
            "@types/react-dom": "^18.2.22",
            "@vitejs/plugin-react": "^4.2.1",
            "typescript": "^5.4.2",
            "vite": "^5.1.6"
          }
        }
        """
    ).strip()
    + "\n",
    "tsconfig.json": dedent(
        """
        {
          "compilerOptions": {
            "target": "ES2020",
            "useDefineForClassFields": true,
            "lib": ["ES2020", "DOM", "DOM.Iterable"],
            "allowJs": false,
            "skipLibCheck": true,
            "esModuleInterop": true,
            "allowSyntheticDefaultImports": true,
            "strict": true,
            "forceConsistentCasingInFileNames": true,
            "module": "ESNext",
            "moduleResolution": "Node",
            "resolveJsonModule": true,
            "isolatedModules": true,
            "noEmit": true,
            "jsx": "react-jsx"
          },
          "include": ["src"],
          "references": []
        }
        """
    ).strip()
    + "\n",
    "vite.config.ts": dedent(
        """
        import { defineConfig } from "vite";
        import react from "@vitejs/plugin-react";

        export default defineConfig({
          plugins: [react()],
          server: {
            port: 5173,
            proxy: {
              "/api": {
                target: "http://localhost:8000",
                changeOrigin: true
              }
            }
          }
        });
        """
    ).strip()
    + "\n",
    "index.html": dedent(
        """
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>FINANO</title>
          </head>
          <body>
            <div id="root"></div>
            <script type="module" src="/src/main.tsx"></script>
          </body>
        </html>
        """
    ).strip()
    + "\n",
    "Dockerfile": dedent(
        """
        FROM node:20-alpine as build

        WORKDIR /app

        COPY package*.json ./
        RUN npm install

        COPY . .
        RUN npm run build

        FROM nginx:alpine
        COPY --from=build /app/dist /usr/share/nginx/html
        COPY nginx.conf /etc/nginx/conf.d/default.conf

        EXPOSE 80
        CMD ["nginx", "-g", "daemon off;"]
        """
    ).strip()
    + "\n",
    "nginx.conf": dedent(
        """
        server {
          listen 80;
          server_name _;

          location / {
            root /usr/share/nginx/html;
            try_files $uri $uri/ /index.html;
          }
        }
        """
    ).strip()
    + "\n",
    "src/main.tsx": dedent(
        """
        import React from "react";
        import ReactDOM from "react-dom/client";
        import { ConfigProvider } from "antd";
        import { BrowserRouter } from "react-router-dom";
        import App from "./App";
        import "./index.css";

        ReactDOM.createRoot(document.getElementById("root")!).render(
          <React.StrictMode>
            <ConfigProvider>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </ConfigProvider>
          </React.StrictMode>
        );
        """
    ).strip()
    + "\n",
    "src/index.css": dedent(
        """
        * {
          box-sizing: border-box;
        }

        body {
          margin: 0;
          font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
          background: #f5f7fb;
          color: #111827;
        }

        .page-stack {
          display: grid;
          gap: 16px;
        }

        .page-actions {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        """
    ).strip()
    + "\n",
    "src/types/user.ts": dedent(
        """
        export interface User {
          id: number;
          username: string;
          email: string;
          created_at: string;
          updated_at: string;
        }

        export interface AuthResponse {
          access_token: string;
          token_type: string;
          user: User;
        }
        """
    ).strip()
    + "\n",
    "src/types/trade.ts": dedent(
        """
        export type TradeDirection = "buy" | "sell";

        export interface Trade {
          id: number;
          user_id: number;
          trade_date: string;
          symbol: string;
          name: string;
          direction: TradeDirection;
          quantity: number;
          price: number;
          amount: number;
          fee: number;
          profit: number;
          platform: string;
          notes?: string | null;
          created_at: string;
          updated_at: string;
        }

        export interface TradeStats {
          total_trades: number;
          win_rate: number;
          profit_factor: number;
          max_drawdown: number;
          total_profit: number;
          avg_profit: number;
        }

        export interface NoteItem {
          id: number;
          user_id: number;
          trade_id?: number | null;
          title: string;
          content: string;
          tags?: string | null;
          created_at: string;
          updated_at: string;
        }

        export interface HotNewsItem {
          id: number;
          title: string;
          summary: string;
          source: string;
          publish_time: string;
          created_at: string;
        }

        export interface PostItem {
          id: number;
          user_id: number;
          title: string;
          content: string;
          likes: number;
          comments: number;
          created_at: string;
          updated_at: string;
        }

        export interface AiAnalysisResult {
          strengths: string[];
          problems: string[];
          suggestions: string[];
        }
        """
    ).strip()
    + "\n",
    "src/services/api.ts": dedent(
        """
        import axios from "axios";
        import { useUserStore } from "../store/userStore";

        export interface ApiEnvelope<T> {
          success: boolean;
          data: T;
          message: string;
        }

        export const api = axios.create({
          baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1"
        });

        api.interceptors.request.use((config) => {
          const token = useUserStore.getState().token;
          if (token) {
            config.headers.Authorization = `Bearer ${token}`;
          }
          return config;
        });

        api.interceptors.response.use(
          (response) => response,
          (error) => {
            const message = error?.response?.data?.message || "请求失败";
            return Promise.reject(new Error(message));
          }
        );
        """
    ).strip()
    + "\n",
    "src/services/user.ts": dedent(
        """
        import { api, ApiEnvelope } from "./api";
        import { AuthResponse, User } from "../types/user";

        export async function login(email: string, password: string) {
          const response = await api.post<ApiEnvelope<AuthResponse>>("/auth/login", { email, password });
          return response.data.data;
        }

        export async function register(username: string, email: string, password: string) {
          const response = await api.post<ApiEnvelope<AuthResponse>>("/auth/register", {
            username,
            email,
            password
          });
          return response.data.data;
        }

        export async function fetchMe() {
          const response = await api.get<ApiEnvelope<User>>("/users/me");
          return response.data.data;
        }
        """
    ).strip()
    + "\n",
    "src/services/trade.ts": dedent(
        """
        import { api, ApiEnvelope } from "./api";
        import { AiAnalysisResult, HotNewsItem, NoteItem, PostItem, Trade, TradeStats } from "../types/trade";

        export async function fetchTrades() {
          const response = await api.get<ApiEnvelope<Trade[]>>("/trades");
          return response.data.data;
        }

        export async function createTrade(payload: Omit<Trade, "id" | "user_id" | "created_at" | "updated_at">) {
          const response = await api.post<ApiEnvelope<Trade>>("/trades", payload);
          return response.data.data;
        }

        export async function importTradeByOcr(file: File) {
          const formData = new FormData();
          formData.append("file", file);
          const response = await api.post<ApiEnvelope<Trade[]>>("/trades/import/ocr", formData, {
            headers: { "Content-Type": "multipart/form-data" }
          });
          return response.data.data;
        }

        export async function fetchTradeStats() {
          const response = await api.get<ApiEnvelope<TradeStats>>("/trades/stats/summary");
          return response.data.data;
        }

        export async function fetchNotes() {
          const response = await api.get<ApiEnvelope<NoteItem[]>>("/notes");
          return response.data.data;
        }

        export async function createNote(payload: { trade_id?: number; title: string; content: string; tags?: string }) {
          const response = await api.post<ApiEnvelope<NoteItem>>("/notes", payload);
          return response.data.data;
        }

        export async function analyzeTrade(tradeId: number) {
          const response = await api.post<ApiEnvelope<AiAnalysisResult>>(`/ai/analyze/${tradeId}`);
          return response.data.data;
        }

        export async function fetchHotNews() {
          const response = await api.get<ApiEnvelope<HotNewsItem[]>>("/hot");
          return response.data.data;
        }

        export async function fetchPosts() {
          const response = await api.get<ApiEnvelope<PostItem[]>>("/community/posts");
          return response.data.data;
        }

        export async function createPost(payload: { title: string; content: string }) {
          const response = await api.post<ApiEnvelope<PostItem>>("/community/posts", payload);
          return response.data.data;
        }

        export async function likePost(postId: number) {
          const response = await api.post<ApiEnvelope<PostItem>>(`/community/posts/${postId}/like`);
          return response.data.data;
        }
        """
    ).strip()
    + "\n",
    "src/store/userStore.ts": dedent(
        """
        import { create } from "zustand";
        import { AuthResponse, User } from "../types/user";

        interface UserState {
          token: string | null;
          currentUser: User | null;
          setAuth: (payload: AuthResponse) => void;
          logout: () => void;
        }

        const TOKEN_KEY = "finano_token";
        const USER_KEY = "finano_user";

        const initialToken = localStorage.getItem(TOKEN_KEY);
        const initialUser = localStorage.getItem(USER_KEY);

        export const useUserStore = create<UserState>((set) => ({
          token: initialToken,
          currentUser: initialUser ? JSON.parse(initialUser) : null,
          setAuth: (payload) => {
            localStorage.setItem(TOKEN_KEY, payload.access_token);
            localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
            set({ token: payload.access_token, currentUser: payload.user });
          },
          logout: () => {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(USER_KEY);
            set({ token: null, currentUser: null });
          }
        }));
        """
    ).strip()
    + "\n",
    "src/utils/format.ts": dedent(
        """
        export function currency(value: number) {
          return new Intl.NumberFormat("zh-CN", {
            style: "currency",
            currency: "CNY",
            maximumFractionDigits: 2
          }).format(value || 0);
        }

        export function percent(value: number) {
          return `${(value || 0).toFixed(2)}%`;
        }
        """
    ).strip()
    + "\n",
    "src/components/UI/PageCard.tsx": dedent(
        """
        import { Card, CardProps } from "antd";

        export function PageCard(props: CardProps) {
          return <Card bordered={false} {...props} />;
        }
        """
    ).strip()
    + "\n",
    "src/components/Chart/ProfitTrendChart.tsx": dedent(
        """
        import { useEffect, useRef } from "react";
        import * as echarts from "echarts";
        import { Trade } from "../../types/trade";

        interface Props {
          trades: Trade[];
        }

        export function ProfitTrendChart({ trades }: Props) {
          const chartRef = useRef<HTMLDivElement | null>(null);

          useEffect(() => {
            if (!chartRef.current) return;
            const chart = echarts.init(chartRef.current);
            const sortedTrades = [...trades].sort((a, b) => a.trade_date.localeCompare(b.trade_date));
            let cumulative = 0;
            const series = sortedTrades.map((item) => {
              cumulative += item.profit;
              return cumulative;
            });
            chart.setOption({
              tooltip: { trigger: "axis" },
              xAxis: {
                type: "category",
                data: sortedTrades.map((item) => item.trade_date)
              },
              yAxis: { type: "value" },
              series: [
                {
                  type: "line",
                  smooth: true,
                  areaStyle: {},
                  data: series
                }
              ]
            });
            const onResize = () => chart.resize();
            window.addEventListener("resize", onResize);
            return () => {
              window.removeEventListener("resize", onResize);
              chart.dispose();
            };
          }, [trades]);

          return <div ref={chartRef} style={{ height: 320 }} />;
        }
        """
    ).strip()
    + "\n",
    "src/components/Layout/AppLayout.tsx": dedent(
        """
        import { BarChartOutlined, BulbOutlined, FileTextOutlined, LoginOutlined, TeamOutlined } from "@ant-design/icons";
        import { Layout, Menu, Typography, Button, Space } from "antd";
        import { ReactNode } from "react";
        import { Link, useLocation, useNavigate } from "react-router-dom";
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
                <div style={{ padding: "14px 12px 18px", textAlign: "center", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                  <Link to="/" style={{ lineHeight: 0 }} aria-label="FINANO 首页">
                    <img src="/brand/finano-mark-dark-bg.png" alt="FINANO" style={{ height: 36, width: "auto", maxWidth: "100%", objectFit: "contain", display: "inline-block" }} />
                  </Link>
                </div>
                <Menu
                  theme="dark"
                  selectedKeys={[location.pathname]}
                  items={[
                    { key: "/", icon: <BarChartOutlined />, label: "仪表盘" },
                    { key: "/trade", icon: <FileTextOutlined />, label: "交易记录" },
                    { key: "/note", icon: <FileTextOutlined />, label: "复盘笔记" },
                    { key: "/ai", icon: <BulbOutlined />, label: "AI 分析" },
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
                  <Link to="/" style={{ lineHeight: 0, display: "flex", alignItems: "center" }} aria-label="FINANO 首页">
                    <img src="/brand/finano-wordmark-light-bg.png" alt="FINANO" style={{ height: 26, width: "auto", objectFit: "contain" }} />
                  </Link>
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
        """
    ).strip()
    + "\n",
    "src/pages/Login/index.tsx": dedent(
        """
        import { Button, Card, Form, Input, Tabs, Typography, message } from "antd";
        import { useNavigate } from "react-router-dom";
        import { login, register } from "../../services/user";
        import { useUserStore } from "../../store/userStore";

        export default function LoginPage() {
          const navigate = useNavigate();
          const setAuth = useUserStore((state) => state.setAuth);

          const onLogin = async (values: { email: string; password: string }) => {
            const result = await login(values.email, values.password);
            setAuth(result);
            message.success("登录成功");
            navigate("/");
          };

          const onRegister = async (values: { username: string; email: string; password: string }) => {
            const result = await register(values.username, values.email, values.password);
            setAuth(result);
            message.success("注册成功");
            navigate("/");
          };

          return (
            <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
              <Card style={{ width: 420 }}>
                <div style={{ textAlign: "center", marginBottom: 20 }}>
                  <img src="/brand/finano-wordmark-light-bg.png" alt="FINANO" style={{ height: 34, width: "auto", margin: "0 auto", display: "block", objectFit: "contain" }} />
                </div>
                <Typography.Paragraph type="secondary">
                  交易记录、复盘分析、热点追踪与社区互动的一体化工作台。
                </Typography.Paragraph>
                <Tabs
                  items={[
                    {
                      key: "login",
                      label: "登录",
                      children: (
                        <Form layout="vertical" onFinish={onLogin}>
                          <Form.Item label="邮箱" name="email" rules={[{ required: true }]}>
                            <Input />
                          </Form.Item>
                          <Form.Item label="密码" name="password" rules={[{ required: true }]}>
                            <Input.Password />
                          </Form.Item>
                          <Button type="primary" htmlType="submit" block>
                            登录
                          </Button>
                        </Form>
                      )
                    },
                    {
                      key: "register",
                      label: "注册",
                      children: (
                        <Form layout="vertical" onFinish={onRegister}>
                          <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
                            <Input />
                          </Form.Item>
                          <Form.Item label="邮箱" name="email" rules={[{ required: true }]}>
                            <Input />
                          </Form.Item>
                          <Form.Item label="密码" name="password" rules={[{ required: true, min: 6 }]}>
                            <Input.Password />
                          </Form.Item>
                          <Button type="primary" htmlType="submit" block>
                            注册并进入系统
                          </Button>
                        </Form>
                      )
                    }
                  ]}
                />
              </Card>
            </div>
          );
        }
        """
    ).strip()
    + "\n",
    "src/pages/Dashboard/index.tsx": dedent(
        """
        import { Col, List, Row, Statistic, Typography } from "antd";
        import { useEffect, useState } from "react";
        import { ProfitTrendChart } from "../../components/Chart/ProfitTrendChart";
        import { PageCard } from "../../components/UI/PageCard";
        import { fetchHotNews, fetchTradeStats, fetchTrades } from "../../services/trade";
        import { HotNewsItem, Trade, TradeStats } from "../../types/trade";
        import { currency, percent } from "../../utils/format";

        export default function DashboardPage() {
          const [stats, setStats] = useState<TradeStats | null>(null);
          const [trades, setTrades] = useState<Trade[]>([]);
          const [hotNews, setHotNews] = useState<HotNewsItem[]>([]);

          useEffect(() => {
            void Promise.all([fetchTradeStats(), fetchTrades(), fetchHotNews()]).then(([tradeStats, tradeItems, news]) => {
              setStats(tradeStats);
              setTrades(tradeItems);
              setHotNews(news);
            });
          }, []);

          return (
            <div className="page-stack">
              <Typography.Title level={3}>仪表盘</Typography.Title>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={12} xl={6}>
                  <PageCard><Statistic title="总交易数" value={stats?.total_trades || 0} /></PageCard>
                </Col>
                <Col xs={24} md={12} xl={6}>
                  <PageCard><Statistic title="胜率" value={percent(stats?.win_rate || 0)} /></PageCard>
                </Col>
                <Col xs={24} md={12} xl={6}>
                  <PageCard><Statistic title="累计收益" value={currency(stats?.total_profit || 0)} /></PageCard>
                </Col>
                <Col xs={24} md={12} xl={6}>
                  <PageCard><Statistic title="盈亏因子" value={stats?.profit_factor || 0} precision={2} /></PageCard>
                </Col>
              </Row>
              <PageCard title="收益曲线">
                <ProfitTrendChart trades={trades} />
              </PageCard>
              <PageCard title="金融热点">
                <List
                  dataSource={hotNews}
                  renderItem={(item) => (
                    <List.Item>
                      <List.Item.Meta title={item.title} description={`${item.summary} 来源：${item.source}`} />
                    </List.Item>
                  )}
                />
              </PageCard>
            </div>
          );
        }
        """
    ).strip()
    + "\n",
    "src/pages/Trade/index.tsx": dedent(
        """
        import { Button, Form, Input, InputNumber, Modal, Select, Space, Table, Upload, message } from "antd";
        import { UploadOutlined } from "@ant-design/icons";
        import { useEffect, useState } from "react";
        import { PageCard } from "../../components/UI/PageCard";
        import { createTrade, fetchTradeStats, fetchTrades, importTradeByOcr } from "../../services/trade";
        import { Trade, TradeStats } from "../../types/trade";
        import { currency } from "../../utils/format";

        export default function TradePage() {
          const [trades, setTrades] = useState<Trade[]>([]);
          const [stats, setStats] = useState<TradeStats | null>(null);
          const [open, setOpen] = useState(false);
          const [form] = Form.useForm();

          const load = async () => {
            const [tradeData, summary] = await Promise.all([fetchTrades(), fetchTradeStats()]);
            setTrades(tradeData);
            setStats(summary);
          };

          useEffect(() => {
            void load();
          }, []);

          return (
            <div className="page-stack">
              <Space className="page-actions">
                <Button type="primary" onClick={() => setOpen(true)}>新增交易</Button>
                <Upload
                  showUploadList={false}
                  beforeUpload={async (file) => {
                    await importTradeByOcr(file);
                    message.success("OCR 导入成功");
                    await load();
                    return false;
                  }}
                >
                  <Button icon={<UploadOutlined />}>导入交割单</Button>
                </Upload>
              </Space>
              <PageCard title={`交易记录（累计收益 ${currency(stats?.total_profit || 0)}）`}>
                <Table
                  rowKey="id"
                  dataSource={trades}
                  pagination={{ pageSize: 8 }}
                  columns={[
                    { title: "日期", dataIndex: "trade_date" },
                    { title: "代码", dataIndex: "symbol" },
                    { title: "名称", dataIndex: "name" },
                    { title: "方向", dataIndex: "direction" },
                    { title: "成交额", dataIndex: "amount", render: (value: number) => currency(value) },
                    { title: "盈亏", dataIndex: "profit", render: (value: number) => currency(value) },
                    { title: "平台", dataIndex: "platform" }
                  ]}
                />
              </PageCard>
              <Modal
                title="新增交易"
                open={open}
                onCancel={() => setOpen(false)}
                onOk={() => form.submit()}
                destroyOnClose
              >
                <Form
                  form={form}
                  layout="vertical"
                  onFinish={async (values) => {
                    await createTrade(values);
                    message.success("交易创建成功");
                    setOpen(false);
                    form.resetFields();
                    await load();
                  }}
                >
                  <Form.Item label="交易日期" name="trade_date" rules={[{ required: true }]}>
                    <Input placeholder="2024-01-05" />
                  </Form.Item>
                  <Form.Item label="证券代码" name="symbol" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item label="证券名称" name="name" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item label="方向" name="direction" initialValue="buy" rules={[{ required: true }]}>
                    <Select options={[{ value: "buy", label: "买入" }, { value: "sell", label: "卖出" }]} />
                  </Form.Item>
                  <Form.Item label="数量" name="quantity" rules={[{ required: true }]}>
                    <InputNumber style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label="价格" name="price" rules={[{ required: true }]}>
                    <InputNumber style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label="成交额" name="amount" rules={[{ required: true }]}>
                    <InputNumber style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label="手续费" name="fee" initialValue={0}>
                    <InputNumber style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label="盈亏" name="profit" initialValue={0}>
                    <InputNumber style={{ width: "100%" }} />
                  </Form.Item>
                  <Form.Item label="平台" name="platform" initialValue="manual">
                    <Input />
                  </Form.Item>
                  <Form.Item label="备注" name="notes">
                    <Input.TextArea rows={3} />
                  </Form.Item>
                </Form>
              </Modal>
            </div>
          );
        }
        """
    ).strip()
    + "\n",
    "src/pages/Note/index.tsx": dedent(
        """
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
        """
    ).strip()
    + "\n",
    "src/pages/AI/index.tsx": dedent(
        """
        import { Button, Card, Empty, List, Select, Space, Typography } from "antd";
        import { useEffect, useState } from "react";
        import { PageCard } from "../../components/UI/PageCard";
        import { analyzeTrade, fetchTrades } from "../../services/trade";
        import { AiAnalysisResult, Trade } from "../../types/trade";

        export default function AIPage() {
          const [trades, setTrades] = useState<Trade[]>([]);
          const [selectedTradeId, setSelectedTradeId] = useState<number>();
          const [result, setResult] = useState<AiAnalysisResult | null>(null);

          useEffect(() => {
            void fetchTrades().then(setTrades);
          }, []);

          return (
            <div className="page-stack">
              <PageCard title="AI 交易分析">
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Select
                    placeholder="选择一笔交易"
                    options={trades.map((item) => ({
                      value: item.id,
                      label: `${item.trade_date} ${item.symbol} ${item.name} ${item.profit}`
                    }))}
                    value={selectedTradeId}
                    onChange={setSelectedTradeId}
                  />
                  <Button
                    type="primary"
                    disabled={!selectedTradeId}
                    onClick={async () => {
                      if (!selectedTradeId) return;
                      setResult(await analyzeTrade(selectedTradeId));
                    }}
                  >
                    生成分析
                  </Button>
                </Space>
              </PageCard>
              {result ? (
                <Card>
                  <Typography.Title level={5}>优点</Typography.Title>
                  <List dataSource={result.strengths} renderItem={(item) => <List.Item>{item}</List.Item>} />
                  <Typography.Title level={5}>问题</Typography.Title>
                  <List dataSource={result.problems} renderItem={(item) => <List.Item>{item}</List.Item>} />
                  <Typography.Title level={5}>建议</Typography.Title>
                  <List dataSource={result.suggestions} renderItem={(item) => <List.Item>{item}</List.Item>} />
                </Card>
              ) : (
                <Empty description="选择交易后生成 AI 分析" />
              )}
            </div>
          );
        }
        """
    ).strip()
    + "\n",
    "src/pages/Community/index.tsx": dedent(
        """
        import { Button, Form, Input, List, Space, message } from "antd";
        import { LikeOutlined } from "@ant-design/icons";
        import { useEffect, useState } from "react";
        import { PageCard } from "../../components/UI/PageCard";
        import { createPost, fetchPosts, likePost } from "../../services/trade";
        import { PostItem } from "../../types/trade";

        export default function CommunityPage() {
          const [posts, setPosts] = useState<PostItem[]>([]);
          const [form] = Form.useForm();

          const load = async () => {
            setPosts(await fetchPosts());
          };

          useEffect(() => {
            void load();
          }, []);

          return (
            <div className="page-stack">
              <PageCard title="发布社区帖子">
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
                  <Button type="primary" htmlType="submit">发布帖子</Button>
                </Form>
              </PageCard>
              <PageCard title="社区动态">
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
        """
    ).strip()
    + "\n",
    "src/App.tsx": dedent(
        """
        import { App as AntdApp, Spin } from "antd";
        import { useEffect, useState } from "react";
        import { Navigate, Route, Routes } from "react-router-dom";
        import { AppLayout } from "./components/Layout/AppLayout";
        import AIPage from "./pages/AI";
        import CommunityPage from "./pages/Community";
        import DashboardPage from "./pages/Dashboard";
        import LoginPage from "./pages/Login";
        import NotePage from "./pages/Note";
        import TradePage from "./pages/Trade";
        import { fetchMe } from "./services/user";
        import { useUserStore } from "./store/userStore";

        function ProtectedLayout({ children }: { children: React.ReactNode }) {
          const token = useUserStore((state) => state.token);
          if (!token) {
            return <Navigate to="/login" replace />;
          }
          return <AppLayout>{children}</AppLayout>;
        }

        export default function App() {
          const token = useUserStore((state) => state.token);
          const setAuth = useUserStore((state) => state.setAuth);
          const logout = useUserStore((state) => state.logout);
          const currentUser = useUserStore((state) => state.currentUser);
          const [loading, setLoading] = useState(Boolean(token && !currentUser));

          useEffect(() => {
            if (!token || currentUser) return;
            void fetchMe()
              .then((user) => setAuth({ access_token: token, token_type: "bearer", user }))
              .catch(() => logout())
              .finally(() => setLoading(false));
          }, [token, currentUser, setAuth, logout]);

          if (loading) {
            return <Spin fullscreen />;
          }

          return (
            <AntdApp>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/" element={<ProtectedLayout><DashboardPage /></ProtectedLayout>} />
                <Route path="/trade" element={<ProtectedLayout><TradePage /></ProtectedLayout>} />
                <Route path="/note" element={<ProtectedLayout><NotePage /></ProtectedLayout>} />
                <Route path="/ai" element={<ProtectedLayout><AIPage /></ProtectedLayout>} />
                <Route path="/community" element={<ProtectedLayout><CommunityPage /></ProtectedLayout>} />
                <Route path="*" element={<Navigate to={token ? "/" : "/login"} replace />} />
              </Routes>
            </AntdApp>
          );
        }
        """
    ).strip()
    + "\n",
}

for relative_path, content in files.items():
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
