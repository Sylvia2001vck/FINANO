import { Button, Progress, Radio, Space, Spin, Typography, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageCard } from "../../components/UI/PageCard";
import { useT } from "../../hooks/useT";
import { getFbtiProfile, postFbtiTest } from "../../services/fbti";
import { useFbtiStore } from "../../store/fbtiStore";
import { useUserStore } from "../../store/userStore";

export default function FbtiTestPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const retake = searchParams.get("retake") === "1";
  const setAuth = useUserStore((s) => s.setAuth);
  const token = useUserStore((s) => s.token);
  const setFbti = useFbtiStore((s) => s.setLast);
  const { t } = useT();
  const [checkingSaved, setCheckingSaved] = useState(!retake);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(Array(8).fill(null));

  const questions = useMemo(
    () => [
      { q: t("fbti.q1"), a: t("fbti.q1a"), b: t("fbti.q1b") },
      { q: t("fbti.q2"), a: t("fbti.q2a"), b: t("fbti.q2b") },
      { q: t("fbti.q3"), a: t("fbti.q3a"), b: t("fbti.q3b") },
      { q: t("fbti.q4"), a: t("fbti.q4a"), b: t("fbti.q4b") },
      { q: t("fbti.q5"), a: t("fbti.q5a"), b: t("fbti.q5b") },
      { q: t("fbti.q6"), a: t("fbti.q6a"), b: t("fbti.q6b") },
      { q: t("fbti.q7"), a: t("fbti.q7a"), b: t("fbti.q7b") },
      { q: t("fbti.q8"), a: t("fbti.q8a"), b: t("fbti.q8b") }
    ],
    [t]
  );

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

  const pct = Math.round(((step + 1) / questions.length) * 100);

  const onNext = () => {
    if (!answers[step]) {
      message.warning(t("fbti.pickOne"));
      return;
    }
    if (step < questions.length - 1) {
      setStep(step + 1);
    } else {
      void submit();
    }
  };

  const submit = async () => {
    if (answers.some((x) => x !== "A" && x !== "B")) {
      message.warning(t("fbti.completeAll"));
      return;
    }
    const ans = answers as string[];
    try {
      const data = await postFbtiTest(ans);
      setFbti(data.fbti_code, data.user_wuxing);
      if (token && data.user) {
        setAuth({ access_token: token, token_type: "bearer", user: data.user });
      }
      message.success(t("fbti.done"));
      navigate("/user-community#fbti", { replace: true });
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("fbti.submitFailed"));
    }
  };

  if (checkingSaved) {
    return <Spin tip={t("common.loading")} />;
  }

  return (
    <div className="page-stack">
      <Typography.Title level={3}>{t("fbti.title")}</Typography.Title>
      <Typography.Paragraph type="secondary">{t("fbti.intro")}</Typography.Paragraph>
      <Progress percent={pct} size="small" style={{ maxWidth: 480 }} />
      <PageCard title={t("fbti.questionProgress", { current: step + 1, total: questions.length })}>
        <Typography.Paragraph strong>{questions[step].q}</Typography.Paragraph>
        <Radio.Group
          value={answers[step]}
          onChange={(e) => {
            const next = [...answers];
            next[step] = e.target.value;
            setAnswers(next);
          }}
        >
          <Space direction="vertical">
            <Radio value="A">{questions[step].a}</Radio>
            <Radio value="B">{questions[step].b}</Radio>
          </Space>
        </Radio.Group>
        <div style={{ marginTop: 24 }}>
          <Space>
            {step > 0 ? <Button onClick={() => setStep(step - 1)}>{t("fbti.prev")}</Button> : null}
            <Button type="primary" onClick={onNext}>
              {step === questions.length - 1 ? t("common.submit") : t("fbti.next")}
            </Button>
          </Space>
        </div>
      </PageCard>
    </div>
  );
}
