import { Button, Card, Form, Input, Tabs, Typography, message } from "antd";
import { useNavigate } from "react-router-dom";
import { FinanoLogo } from "../../components/FinanoLogo";
import { postWarmFundCatalog } from "../../services/agent";
import { login, register } from "../../services/user";
import { useUserStore } from "../../store/userStore";

export default function LoginPage() {
  const navigate = useNavigate();
  const setAuth = useUserStore((state) => state.setAuth);

  const onLogin = async (values: { email: string; password: string }) => {
    try {
      const result = await login(values.email, values.password);
      setAuth(result);
      void postWarmFundCatalog().catch(() => {
        /* 预热失败不影响登录；MAFB 页会重试 */
      });
      message.success("登录成功");
      navigate("/");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "登录失败");
    }
  };

  const onRegister = async (values: { username: string; email: string; password: string }) => {
    try {
      const result = await register(values.username, values.email, values.password);
      setAuth(result);
      void postWarmFundCatalog().catch(() => {});
      message.success("注册成功");
      navigate("/");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "注册失败");
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <Card style={{ width: 420 }}>
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <FinanoLogo variant="wordmark" height={44} style={{ margin: "0 auto" }} />
        </div>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center" }}>
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
