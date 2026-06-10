import { Button, Card, Form, Input, Tabs, Typography, message } from "antd";
import { useNavigate } from "react-router-dom";
import { FinanoLogo } from "../../components/FinanoLogo";
import { LocaleSwitcher } from "../../components/LocaleSwitcher";
import { useT } from "../../hooks/useT";
import { postWarmFundCatalog } from "../../services/agent";
import { login, register } from "../../services/user";
import { useUserStore } from "../../store/userStore";

export default function LoginPage() {
  const navigate = useNavigate();
  const setAuth = useUserStore((state) => state.setAuth);
  const { t } = useT();

  const onLogin = async (values: { email: string; password: string }) => {
    try {
      const result = await login(values.email, values.password);
      setAuth(result);
      void postWarmFundCatalog().catch(() => {
        /* 预热失败不影响登录；MAFB 页会重试 */
      });
      message.success(t("login.success"));
      navigate("/");
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("login.failed"));
    }
  };

  const onRegister = async (values: { username: string; email: string; password: string }) => {
    try {
      const result = await register(values.username, values.email, values.password);
      setAuth(result);
      void postWarmFundCatalog().catch(() => {});
      message.success(t("login.registerSuccess"));
      navigate("/");
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("login.registerFailed"));
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <Card style={{ width: 420 }}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
          <LocaleSwitcher />
        </div>
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <FinanoLogo variant="wordmark" height={44} style={{ margin: "0 auto" }} />
        </div>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center" }}>
          {t("login.tagline")}
        </Typography.Paragraph>
        <Tabs
          items={[
            {
              key: "login",
              label: t("login.tabLogin"),
              children: (
                <Form layout="vertical" onFinish={onLogin}>
                  <Form.Item label={t("login.email")} name="email" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item label={t("login.password")} name="password" rules={[{ required: true }]}>
                    <Input.Password />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block>
                    {t("login.submitLogin")}
                  </Button>
                </Form>
              )
            },
            {
              key: "register",
              label: t("login.tabRegister"),
              children: (
                <Form layout="vertical" onFinish={onRegister}>
                  <Form.Item label={t("login.username")} name="username" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item label={t("login.email")} name="email" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item label={t("login.password")} name="password" rules={[{ required: true, min: 6 }]}>
                    <Input.Password />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block>
                    {t("login.submitRegister")}
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
