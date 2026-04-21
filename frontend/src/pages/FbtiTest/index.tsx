import { Button, Progress, Radio, Space, Spin, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { getFbtiProfile, postFbtiTest } from "../../services/fbti";
import { useFbtiStore } from "../../store/fbtiStore";
import { useUserStore } from "../../store/userStore";

const QUESTIONS: { q: string; a: string; b: string }[] = [
  { q: "你的投资风险偏好？", a: "本金安全第一（R）", b: "追求高收益，接受波动（S）" },
  { q: "你的持仓周期？", a: "1 年以上长期持有（L）", b: "1 个月内短线操作（T）" },
  { q: "你如何做决策？", a: "看数据 / 净值 / 回撤（D）", b: "凭直觉 / 热点 / 新闻（F）" },
  { q: "你的仓位习惯？", a: "重仓集中 3 只内（C）", b: "分散持仓 10 只以上（A）" },
  { q: "下跌时你会？", a: "加仓补仓（R）", b: "止损卖出（S）" },
  { q: "收益目标？", a: "年化 10% 稳健（L）", b: "年化 30%+ 暴利（T）" },
  { q: "选基优先看？", a: "历史业绩数据（D）", b: "基金经理口碑（F）" },
  { q: "资产配置？", a: "单一赛道重仓（C）", b: "股债均衡分散（A）" }
];

export default function FbtiTestPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const retake = searchParams.get("retake") === "1";
  const setAuth = useUserStore((s) => s.setAuth);
  const token = useUserStore((s) => s.token);
  const setFbti = useFbtiStore((s) => s.setLast);
  const [checkingSaved, setCheckingSaved] = useState(!retake);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(Array(8).fill(null));

  useEffect(() => {
    if (retake) {
      setCheckingSaved(false);
      return;
    }
    void getFbtiProfile()
      .then((d) => {
        if (d.fbti_profile) {
          navigate("/user-community#fbti", { replace: true });
        }
      })
      .catch(() => {})
      .finally(() => setCheckingSaved(false));
  }, [retake, navigate]);

  const pct = Math.round(((step + 1) / QUESTIONS.length) * 100);

  const onNext = () => {
    if (!answers[step]) {
      message.warning("请选择一个选项");
      return;
    }
    if (step < QUESTIONS.length - 1) {
      setStep(step + 1);
    } else {
      void submit();
    }
  };

  const submit = async () => {
    if (answers.some((x) => x !== "A" && x !== "B")) {
      message.warning("请完成全部题目");
      return;
    }
    const ans = answers as string[];
    try {
      const data = await postFbtiTest(ans);
      setFbti(data.fbti_code, data.user_wuxing);
      if (token && data.user) {
        setAuth({ access_token: token, token_type: "bearer", user: data.user });
      }
      message.success("测试完成");
      navigate("/user-community#fbti", { replace: true });
    } catch (e) {
      message.error(e instanceof Error ? e.message : "提交失败");
    }
  };

  if (checkingSaved) {
    return <Spin tip="加载中…" />;
  }

  return (
    <div className="page-stack">
      <Typography.Title level={3}>FBTI 金融人格测试</Typography.Title>
      <Typography.Paragraph type="secondary">
        共 8 题，单选，约 1 分钟完成。结果用于行为金融学演示画像，不构成投资建议。
      </Typography.Paragraph>
      <Progress percent={pct} size="small" style={{ maxWidth: 480 }} />
      <PageCard title={`第 ${step + 1} / ${QUESTIONS.length} 题`}>
        <Typography.Paragraph strong>{QUESTIONS[step].q}</Typography.Paragraph>
        <Radio.Group
          value={answers[step]}
          onChange={(e) => {
            const next = [...answers];
            next[step] = e.target.value;
            setAnswers(next);
          }}
        >
          <Space direction="vertical">
            <Radio value="A">{QUESTIONS[step].a}</Radio>
            <Radio value="B">{QUESTIONS[step].b}</Radio>
          </Space>
        </Radio.Group>
        <div style={{ marginTop: 24 }}>
          <Space>
            {step > 0 ? <Button onClick={() => setStep(step - 1)}>上一题</Button> : null}
            <Button type="primary" onClick={onNext}>
              {step === QUESTIONS.length - 1 ? "提交" : "下一题"}
            </Button>
          </Space>
        </div>
      </PageCard>
    </div>
  );
}
