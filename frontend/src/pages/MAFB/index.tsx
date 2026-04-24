import { LineChartOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Descriptions,
  Form,
  Input,
  List,
  Row,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { useEffect, useRef, useState } from "react";
import { FundCodeOcrButton } from "../../components/FundCodeOcrButton";
import { FundNavCurvePanel } from "../../components/FundNavCurvePanel";
import type { FundNavCurvePanelHandle } from "../../components/FundNavCurvePanel";
import { PageCard } from "../../components/UI/PageCard";
import {
  addMyAgentFunds,
  getMafbTaskStatus,
  getFundCatalogStatus,
  listAgentFunds,
  postLlmProbe,
  postWarmFundCatalog,
  removeMyAgentFund,
  runMafbAsync,
  fetchSimilarFunds,
  type AgentFundsListResponse,
  type ListAgentFundsParams,
  type SimilarFundRow
} from "../../services/agent";
import { fetchFundLsjzJson } from "../../services/fundNav";

function pctOrDash(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

/** RAG 片段列表单行预览上限 */
function clipRagPreview(v: unknown, maxLen = 72): string {
  const s = String(v ?? "");
  return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s;
}

function fmtDate(d: Date): string {
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const dd = `${d.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function PositionAdviceView({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <Typography.Text type="secondary">暂无仓位建议（先完成流水线或检查画像数据）。</Typography.Text>
    );
  }
  const note = data.note != null && String(data.note).trim() ? String(data.note) : null;
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="风险等级（演示刻度）">{String(data.risk_level ?? "—")}</Descriptions.Item>
        <Descriptions.Item label="建议权益类仓位上限">{pctOrDash(data.suggested_max_equity_weight)}</Descriptions.Item>
        <Descriptions.Item label="流年权益上限（规则演示）" span={2}>
          {pctOrDash(data.liunian_equity_cap)}
        </Descriptions.Item>
      </Descriptions>
      {note ? (
        <Typography.Paragraph style={{ marginBottom: 0 }} type="secondary">
          {note}
        </Typography.Paragraph>
      ) : null}
    </Space>
  );
}

function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function pct(v: unknown, digits = 1): string {
  const n = num(v);
  if (n == null) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

type LaneKey = "profiling" | "fundamental" | "technical" | "risk" | "attribution";

function buildTraceLanes(lines: string[]) {
  const lanes: Record<LaneKey, string[]> = {
    profiling: [],
    fundamental: [],
    technical: [],
    risk: [],
    attribution: [],
  };
  const running: Record<LaneKey, boolean> = {
    profiling: false,
    fundamental: false,
    technical: false,
    risk: false,
    attribution: false,
  };

  const push = (k: LaneKey, msg: string) => {
    lanes[k].push(msg);
    if (lanes[k].length > 14) lanes[k] = lanes[k].slice(-14);
  };

  for (const line of lines) {
    const low = line.toLowerCase();
    const has = (kw: string) => low.includes(kw);
    const target: LaneKey | null = has("[profiling]") || has("profiling") || has("profile") || line.includes("画像")
      ? "profiling"
      : has("[fundamental]") || has("fundamental") || line.includes("基本面")
      ? "fundamental"
      : has("[technical]") || has("technical") || line.includes("技术面")
      ? "technical"
      : has("[risk]") || has("risk") || line.includes("风控")
      ? "risk"
      : has("[attribution]") || has("attribution") || line.includes("归因") || line.includes("风格")
      ? "attribution"
      : null;
    if (!target) continue;
    push(target, line);
    if (has("agent_start") || has("llm_channel_start") || has("stage:")) running[target] = true;
    if (has("agent_done") || has("agent_fallback") || has("stage: 阶段完成")) running[target] = false;
  }

  return { lanes, running };
}

function FundamentalInsightView({
  fund,
  score,
  reason,
  runTrace
}: {
  fund: Record<string, unknown> | undefined;
  score: number | undefined;
  reason: string | undefined;
  runTrace: string[];
}) {
  if (!fund) {
    return <Typography.Text type="secondary">暂无基本面数据。</Typography.Text>;
  }

  const sourceNotes = (fund.source_notes as string[] | undefined) || [];
  const managerScore = num(fund.manager_score);
  const managerRet = num(fund.manager_return_annual);
  const top10 = num(fund.stock_top10_concentration);
  const eqRatio = num(fund.stock_equity_ratio);
  const drift = num(fund.holding_drift);
  const qn = num(fund.quarter_samples);

  const concentrationTag =
    top10 == null ? "未知" : top10 > 0.6 ? "持仓极度集中" : top10 < 0.3 ? "极其分散" : "集中度中性";
  const driftTag = drift == null ? "未知" : drift > 0.25 ? "风格剧变" : drift > 0.15 ? "风格偏移" : "风格稳定";

  const llmTrace = runTrace.filter((line) => /fundamental|llm_raw/i.test(line)).slice(-10);

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="基本面分数">{score ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="经理能力得分">{managerScore ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="经理年化收益">{managerRet == null ? "—" : pct(managerRet, 2)}</Descriptions.Item>
        <Descriptions.Item label="前十大持仓集中度">{pct(top10, 1)}</Descriptions.Item>
        <Descriptions.Item label="权益仓位">{pct(eqRatio, 1)}</Descriptions.Item>
        <Descriptions.Item label="风格漂移（季度均值）">{pct(drift, 1)}</Descriptions.Item>
        <Descriptions.Item label="季度样本数">{qn ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="数据源状态">
          <Space wrap>
            {sourceNotes.length
              ? sourceNotes.map((s) => (
                  <Tag key={s} color={/ok|=/.test(s) ? "green" : "orange"}>
                    {s}
                  </Tag>
                ))
              : "—"}
          </Space>
        </Descriptions.Item>
      </Descriptions>

      <Space wrap>
        <Tag color={top10 != null && top10 > 0.6 ? "red" : top10 != null && top10 < 0.3 ? "blue" : "gold"}>
          {concentrationTag}
        </Tag>
        <Tag color={drift != null && drift > 0.25 ? "red" : drift != null && drift > 0.15 ? "orange" : "green"}>
          {driftTag}
        </Tag>
      </Space>

      <Collapse
        bordered
        items={[
          {
            key: "fund-llm-reason",
            label: "大模型基本面推演（原文）",
            children: reason ? (
              <Typography.Paragraph style={{ marginBottom: 0 }}>{reason}</Typography.Paragraph>
            ) : (
              <Typography.Text type="secondary">暂无基本面推演。</Typography.Text>
            )
          },
          {
            key: "fund-llm-trace",
            label: "调用链路（trace）",
            children: llmTrace.length ? (
              <List
                size="small"
                dataSource={llmTrace}
                renderItem={(line) => (
                  <List.Item>
                    <Typography.Text style={{ fontSize: 12 }}>{line}</Typography.Text>
                  </List.Item>
                )}
              />
            ) : (
              <Typography.Text type="secondary">暂无 trace 片段。</Typography.Text>
            )
          }
        ]}
      />
    </Space>
  );
}

function NewsSignalView({ fund }: { fund: Record<string, unknown> | undefined }) {
  const news = (fund?.news_signals as Record<string, unknown> | undefined) || {};
  const fns = (news.fundamental_news as Record<string, unknown>[] | undefined) || [];
  const ras = (news.risk_alerts as Record<string, unknown>[] | undefined) || [];
  const policy = Number(news.policy_signal_score ?? 0);
  const swan = Number(news.black_swan_score ?? 0);
  const kws = (news.keywords as string[] | undefined) || [];
  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="新闻源">{String(news.source ?? "—")}</Descriptions.Item>
        <Descriptions.Item label="抓取时间">{String(news.fetched_at ?? "—")}</Descriptions.Item>
        <Descriptions.Item label="政策扰动评分">{Number.isFinite(policy) ? policy.toFixed(2) : "0.00"}</Descriptions.Item>
        <Descriptions.Item label="黑天鹅评分">{Number.isFinite(swan) ? swan.toFixed(2) : "0.00"}</Descriptions.Item>
        <Descriptions.Item label="关键词" span={2}>
          <Space wrap>
            {kws.length ? kws.map((k) => <Tag key={k}>{k}</Tag>) : "—"}
          </Space>
        </Descriptions.Item>
      </Descriptions>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Typography.Title level={5} style={{ marginBottom: 8 }}>
            Fundamental 关注（逻辑变动）
          </Typography.Title>
          <List
            size="small"
            dataSource={fns}
            locale={{ emptyText: "暂无政策相关舆情" }}
            renderItem={(it) => (
              <List.Item>
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Typography.Text strong>{String(it.title ?? "—")}</Typography.Text>
                  <Typography.Paragraph style={{ marginBottom: 0 }} type="secondary">
                    {String(it.summary ?? "")}
                  </Typography.Paragraph>
                  <Space wrap>
                    {((it.tags as string[] | undefined) || []).map((t) => (
                      <Tag key={`${String(it.title)}-${t}`} color="blue">
                        {t}
                      </Tag>
                    ))}
                    {it.url ? (
                      <a href={String(it.url)} target="_blank" rel="noreferrer">
                        查看原文
                      </a>
                    ) : null}
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        </Col>
        <Col xs={24} lg={12}>
          <Typography.Title level={5} style={{ marginBottom: 8 }}>
            Risk 关注（黑天鹅）
          </Typography.Title>
          <List
            size="small"
            dataSource={ras}
            locale={{ emptyText: "暂无负面风险舆情" }}
            renderItem={(it) => (
              <List.Item>
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Typography.Text strong>{String(it.title ?? "—")}</Typography.Text>
                  <Typography.Paragraph style={{ marginBottom: 0 }} type="secondary">
                    {String(it.summary ?? "")}
                  </Typography.Paragraph>
                  <Space wrap>
                    <Tag color="red">negative={Number(it.negative_score ?? 0).toFixed(2)}</Tag>
                    {((it.tags as string[] | undefined) || []).map((t) => (
                      <Tag key={`${String(it.title)}-${t}`} color="volcano">
                        {t}
                      </Tag>
                    ))}
                    {it.url ? (
                      <a href={String(it.url)} target="_blank" rel="noreferrer">
                        查看原文
                      </a>
                    ) : null}
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        </Col>
      </Row>
    </Space>
  );
}

function RiskAuxFactorView({ fund }: { fund: Record<string, unknown> | undefined }) {
  const riskSummary = (fund?.risk_summary as Record<string, unknown> | undefined) || {};
  const newsAux = (riskSummary.news_aux as Record<string, unknown> | undefined) || {};
  const ratio = num(newsAux.contribution_ratio);
  const penalty = num(newsAux.penalty);
  const basePenalty = num(newsAux.base_penalty);
  const black = num(newsAux.black_swan_score);
  const policy = num(newsAux.policy_signal_score);
  const ratioTagColor = ratio == null ? "default" : ratio <= 0.15 ? "green" : ratio <= 0.3 ? "gold" : "red";

  if (!Object.keys(riskSummary).length) {
    return <Typography.Text type="secondary">暂无风控结构化快照。</Typography.Text>;
  }

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Alert
        type="info"
        showIcon
        message="新闻因子只做辅助修正，不替代量化风控主指标"
        description="主指标仍由回撤、波动率、VaR、集中度、流动性与相关性共同决定。"
      />
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="新闻辅助贡献占比">
          <Space wrap>
            <Tag color={ratioTagColor}>{ratio == null ? "—" : pct(ratio, 1)}</Tag>
            <Typography.Text type="secondary">= news_penalty / (base_penalty + news_penalty)</Typography.Text>
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="新闻惩罚项">{penalty == null ? "—" : penalty.toFixed(3)}</Descriptions.Item>
        <Descriptions.Item label="量化基础惩罚项">{basePenalty == null ? "—" : basePenalty.toFixed(3)}</Descriptions.Item>
        <Descriptions.Item label="黑天鹅分">{black == null ? "—" : black.toFixed(2)}</Descriptions.Item>
        <Descriptions.Item label="政策扰动分">{policy == null ? "—" : policy.toFixed(2)}</Descriptions.Item>
      </Descriptions>
    </Space>
  );
}

export default function MAFBPage() {
  const [form] = Form.useForm();
  const watchedFundCode = Form.useWatch("fund_code", form) as string | undefined;
  const [loading, setLoading] = useState(false);
  const [runStage, setRunStage] = useState<string | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [fundBundle, setFundBundle] = useState<AgentFundsListResponse | null>(null);
  const [fundSearch, setFundSearch] = useState("");
  const [fundPanelTab, setFundPanelTab] = useState<"catalog" | "random" | "my_pool">("catalog");
  const [catalogPageSize] = useState(10);
  const [catalogOffset, setCatalogOffset] = useState(0);
  const [randTrack, setRandTrack] = useState("");
  const [randType, setRandType] = useState("");
  const [randEtfOnly, setRandEtfOnly] = useState(false);
  const [randRiskMin, setRandRiskMin] = useState("");
  const [randRiskMax, setRandRiskMax] = useState("");
  const [poolBulkInput, setPoolBulkInput] = useState("");
  const [catalogBootstrapLoading, setCatalogBootstrapLoading] = useState(true);
  const [fundTableLoading, setFundTableLoading] = useState(false);
  const [catalogInitError, setCatalogInitError] = useState<string | null>(null);
  const [initCatalogMode, setInitCatalogMode] = useState("static");
  const [catalogRetryNonce, setCatalogRetryNonce] = useState(0);
  const [simRefCode, setSimRefCode] = useState("");
  const [simFeatureRows, setSimFeatureRows] = useState<SimilarFundRow[]>([]);
  const [simBusy, setSimBusy] = useState(false);
  const fundNavRef = useRef<FundNavCurvePanelHandle>(null);
  const [runTrace, setRunTrace] = useState<string[]>([]);
  const [runLogVisible, setRunLogVisible] = useState(false);
  const [runLogStatus, setRunLogStatus] = useState<"running" | "success" | "failed" | null>(null);
  const [runLogCollapsed, setRunLogCollapsed] = useState(false);
  const [runLogTitle, setRunLogTitle] = useState("调用记录");
  const navWarmRef = useRef<Set<string>>(new Set());
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeResult, setProbeResult] = useState<Record<string, unknown> | null>(null);
  const [navPrimaryStatus, setNavPrimaryStatus] = useState<string>("");

  const preheatFundNav = async (codeRaw?: string) => {
    const c = String(codeRaw ?? "").trim();
    if (!/^\d{6}$/.test(c)) return;
    const end = new Date();
    const start = new Date(end);
    start.setMonth(start.getMonth() - 1);
    const key = `${c}|${fmtDate(start)}|${fmtDate(end)}`;
    if (navWarmRef.current.has(key)) return;
    navWarmRef.current.add(key);
    try {
      await fetchFundLsjzJson(c, { startDate: fmtDate(start), endDate: fmtDate(end) });
    } catch {
      /* 预热失败不影响主流程 */
    }
  };

  const fetchFunds = (params: ListAgentFundsParams) => {
    setFundTableLoading(true);
    void listAgentFunds(params)
      .then(setFundBundle)
      .catch((e) => {
        message.error(e instanceof Error ? e.message : "加载基金列表失败");
      })
      .finally(() => setFundTableLoading(false));
  };

  const loadCatalogPage = (offset: number, q?: string) => {
    setCatalogOffset(offset);
    fetchFunds({
      view: "catalog",
      limit: catalogPageSize,
      offset,
      q: q?.trim() || undefined
    });
  };

  const loadFundsSearch = () => {
    loadCatalogPage(0, fundSearch);
  };

  const addOneToPool = async (code: string) => {
    try {
      const r = await addMyAgentFunds([code]);
      message.success(`已加入自选（+${r.added}）`);
      if (fundPanelTab === "my_pool") loadMyPool();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加入失败");
    }
  };

  const runRandomSample = () => {
    const rmin = randRiskMin.trim() === "" ? undefined : Number(randRiskMin);
    const rmax = randRiskMax.trim() === "" ? undefined : Number(randRiskMax);
    fetchFunds({
      view: "random",
      limit: 400,
      q: fundSearch.trim() || undefined,
      track: randTrack.trim() || undefined,
      fundType: randType.trim() || undefined,
      etfOnly: randEtfOnly || undefined,
      riskMin: Number.isFinite(rmin) ? rmin : undefined,
      riskMax: Number.isFinite(rmax) ? rmax : undefined
    });
  };

  const loadMyPool = () => {
    fetchFunds({ view: "my_pool", limit: 5000, offset: 0 });
  };

  const removePoolRow = async (code: string) => {
    try {
      const r = await removeMyAgentFund(code);
      setFundBundle((prev) =>
        prev
          ? { ...prev, items: r.items, total: r.total, view: "my_pool" }
          : {
              items: r.items,
              total: r.total,
              catalog_mode: "static",
              limit: r.total,
              offset: 0,
              view: "my_pool"
            }
      );
      message.success("已移除");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "移除失败");
    }
  };

  const bulkAddPool = async () => {
    const parts = poolBulkInput.split(/[\s,，;；]+/).filter(Boolean);
    if (!parts.length) {
      message.warning("请输入至少一个 6 位代码");
      return;
    }
    try {
      const r = await addMyAgentFunds(parts);
      message.success(`已处理，新增 ${r.added} 条`);
      setPoolBulkInput("");
      if (fundPanelTab === "my_pool") loadMyPool();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加入失败");
    }
  };

  useEffect(() => {
    let cancelled = false;
    const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

    async function bootstrapCatalog() {
      setCatalogInitError(null);
      setCatalogBootstrapLoading(true);
      try {
        let st = await getFundCatalogStatus();
        if (cancelled) return;
        setInitCatalogMode(st.catalog_mode || "static");
        if (st.catalog_mode !== "eastmoney_full") {
          await listAgentFunds({ view: "catalog", limit: 10, offset: 0 }).then((d) => {
            if (!cancelled) setFundBundle(d);
          });
          return;
        }
        if (!st.cached) {
          await postWarmFundCatalog();
        }
        let loadFailed: string | null = null;
        for (let i = 0; i < 600 && !cancelled; i++) {
          st = await getFundCatalogStatus();
          if (st.cached) break;
          if (st.error && !st.busy) {
            loadFailed = st.error;
            break;
          }
          await sleep(500);
        }
        if (cancelled) return;
        if (loadFailed) {
          setCatalogInitError(loadFailed);
          return;
        }
        await listAgentFunds({ view: "catalog", limit: 10, offset: 0 }).then((d) => {
          if (!cancelled) setFundBundle(d);
        });
      } catch (e) {
        if (!cancelled) setCatalogInitError(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (!cancelled) setCatalogBootstrapLoading(false);
      }
    }

    void bootstrapCatalog();
    return () => {
      cancelled = true;
    };
  }, [catalogRetryNonce]);

  const funds = fundBundle?.items ?? [];
  const fundTotal = fundBundle?.total ?? 0;
  const catalogMode = fundBundle?.catalog_mode ?? "static";
  const sampleSeed = fundBundle?.sample_seed;
  const filterTotal = fundBundle?.filter_total;

  const runSimilarityLookup = async (codeArg?: string) => {
    const c = (codeArg ?? watchedFundCode ?? "").trim();
    if (!/^\d{6}$/.test(c)) {
      message.warning("请输入 6 位基金代码");
      return;
    }
    setSimBusy(true);
    setSimRefCode(c);
    try {
      const feat = await fetchSimilarFunds(c, 10);
      setSimFeatureRows(feat.similar || []);
      if (!(feat.similar?.length)) {
        message.info("未得到相似结果（目录或净值数据不足）");
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "查询失败");
      setSimFeatureRows([]);
    } finally {
      setSimBusy(false);
    }
  };

  const runLlmProbe = async () => {
    setProbeBusy(true);
    try {
      const v = await form.validateFields(["fund_code"]);
      const fundCode = String(v.fund_code ?? "").trim();
      const data = await postLlmProbe({
        timeout_sec: 10,
        prompt: `请只返回 JSON：{"agent_name":"risk","score":0,"reason":"历史不代表未来"}。基金代码：${fundCode}`
      });
      setProbeResult(data as unknown as Record<string, unknown>);
      message.info(data.ok ? "探针成功：模型通道可用" : "探针失败：请看状态码与错误信息");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "探针失败");
    } finally {
      setProbeBusy(false);
    }
  };

  const onRun = async (values: { fund_code: string; include_fbti?: boolean }) => {
    setLoading(true);
    setRunStage("正在提交任务…");
    setRunTrace([]);
    setRunLogVisible(true);
    setRunLogStatus("running");
    setRunLogCollapsed(false);
    setRunLogTitle(`调用记录 · ${values.fund_code.trim()} · ${new Date().toLocaleTimeString()}`);
    try {
      const submit = await runMafbAsync({
        fund_code: values.fund_code.trim(),
        include_fbti: values.include_fbti !== false
      });
      let cursor = 0;
      let done = false;
      let finalData: Record<string, unknown> | null = null;
      const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
      for (let i = 0; i < 900; i++) {
        const st = await getMafbTaskStatus(submit.task_id, cursor);
        if (st.stage_label) {
          setRunStage(`正在执行：${st.stage_label}`);
        }
        const evs = st.trace_events || [];
        if (evs.length) {
          setRunTrace((prev) =>
            [
              ...prev,
              ...evs.map((e) => `${e.node ? `[${e.node}] ` : ""}${e.kind || "event"}: ${e.message || ""}`)
            ].slice(-28)
          );
        }
        cursor = typeof st.next_cursor === "number" ? st.next_cursor : cursor + evs.length;
        if (st.done) {
          done = true;
          if (st.status === "completed" && st.data?.final_report) {
            finalData = st.data.final_report as Record<string, unknown>;
          } else {
            throw new Error(st.error || "任务失败");
          }
          break;
        }
        await sleep(1000);
      }
      if (!done) {
        throw new Error("任务执行时间过长，请稍后在结果区重试查询");
      }
      if (finalData) setReport(finalData);
      setRunLogStatus("success");
      setRunLogCollapsed(true);
      message.success("MAFB 流水线执行完成");
    } catch (error) {
      setRunLogStatus("failed");
      setRunLogCollapsed(false);
      message.error(error instanceof Error ? error.message : "执行失败");
    } finally {
      setLoading(false);
    }
  };

  const scores = (report?.scores as Record<string, number> | undefined) || {};
  const singleFundAnalysis = String(report?.single_fund_analysis ?? "");
  const userProf = report?.user_profile as Record<string, unknown> | undefined;
  const chain = (report?.reasoning_chain as string[] | undefined) || [];
  const position = report?.position_advice as Record<string, unknown> | undefined;
  const verdict = report?.verdict as string | undefined;
  const scoreBreakdown = (report?.score_breakdown as Record<string, Record<string, unknown>> | undefined) || {};
  const agentReasons = (report?.reasons as Record<string, string> | undefined) || {};
  const complianceBlock = report?.compliance as Record<string, unknown> | undefined;
  const ragChunks = (report?.rag_chunks as string[] | undefined) || [];
  const fundData = report?.fund as Record<string, unknown> | undefined;
  const riskSummary = (fundData?.risk_summary as Record<string, unknown> | undefined) || {};
  const riskNewsAux = (riskSummary.news_aux as Record<string, unknown> | undefined) || {};
  const riskNewsAuxRatio = num(riskNewsAux.contribution_ratio);
  const complianceNotes = ((complianceBlock?.notes as string[] | undefined) || []).map((x) => String(x ?? ""));
  const riskWarningNotes = complianceNotes.filter((n) => n.startsWith("风控告警：") || n.startsWith("风控警告："));
  const commonComplianceNotes = complianceNotes.filter((n) => !riskWarningNotes.includes(n));
  const lanePack = buildTraceLanes(runTrace);
  const laneItems: Array<{ key: LaneKey; title: string }> = [
    { key: "profiling", title: "Profile 泳道" },
    { key: "fundamental", title: "Fundamental 泳道" },
    { key: "technical", title: "Technical 泳道" },
    { key: "risk", title: "Risk 泳道" },
    { key: "attribution", title: "归因泳道" },
  ];

  /** MAFB 与相似查询互斥：避免并行请求导致结果与当前输入错位 */
  const agentOpBusy = loading || simBusy;

  return (
    <div className="page-stack">
      <Typography.Title level={3}>MAFB 多智能体控制台</Typography.Title>
      <Typography.Paragraph type="secondary">
        输入 6 位基金代码后，中间「查询基金净值」拉取东财历史净值；拉取成功后切换「近一月 / 近三月」等区间会<strong>自动重新拉取</strong>。「运行 MAFB 流水线」与「查询相似 TOP10」互斥需排队；净值查询可与二者并行。
        勾选「纳入 FBTI」时，画像与资产配置会使用账户已保存的金融人格；不勾选则仅用账户风险偏好档位（不含人格偏好摘要）。
      </Typography.Paragraph>

      <PageCard title="基金代码与运行">
        {runLogVisible ? (
          runLogStatus === "failed" ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 16 }}
              message={runStage || "运行失败"}
              description={
                <div style={{ maxHeight: 200, overflow: "auto", fontSize: 12 }}>
                  {runTrace.map((line, idx) => (
                    <div key={`${idx}-${line}`}>{line}</div>
                  ))}
                </div>
              }
            />
          ) : runLogStatus === "success" ? (
            <Collapse
              style={{ marginBottom: 16 }}
              activeKey={runLogCollapsed ? [] : ["log"]}
              onChange={(keys) => setRunLogCollapsed(!(keys as string[]).includes("log"))}
              items={[
                {
                  key: "log",
                  label: `${runLogTitle}（成功，${runTrace.length} 条）`,
                  children: (
                    <div style={{ maxHeight: 200, overflow: "auto", fontSize: 12 }}>
                      {runTrace.map((line, idx) => (
                        <div key={`${idx}-${line}`}>{line}</div>
                      ))}
                    </div>
                  )
                }
              ]}
            />
          ) : (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={runStage || "运行中"}
              description={
                runTrace.length ? (
                  <div style={{ maxHeight: 160, overflow: "auto", fontSize: 12 }}>
                    {runTrace.map((line, idx) => (
                      <div key={`${idx}-${line}`}>{line}</div>
                    ))}
                  </div>
                ) : undefined
              }
            />
          )
        ) : null}
        {runLogVisible ? (
          <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
            {laneItems.map((lane) => {
              const rows = lanePack.lanes[lane.key];
              const active = lanePack.running[lane.key];
              return (
                <Col xs={24} md={12} xl={6} key={lane.key}>
                  <Card
                    size="small"
                    title={
                      <Space>
                        <span>{lane.title}</span>
                        <Tag color={active ? "processing" : "default"}>{active ? "运行中" : "待机/已完成"}</Tag>
                      </Space>
                    }
                    bodyStyle={{ maxHeight: 160, overflow: "auto", fontSize: 12 }}
                  >
                    {rows.length ? (
                      rows.map((x, i) => (
                        <div key={`${lane.key}-${i}`}>{x}</div>
                      ))
                    ) : (
                      <Typography.Text type="secondary">暂无该泳道事件</Typography.Text>
                    )}
                  </Card>
                </Col>
              );
            })}
          </Row>
        ) : null}
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            fund_code: "510300",
            include_fbti: true
          }}
        >
          <Form.Item
            label="基金 / ETF 代码"
            name="fund_code"
            rules={[
              { required: true, message: "请输入基金代码" },
              { pattern: /^\d{6}$/, message: "须为 6 位数字代码" }
            ]}
          >
            <Space.Compact style={{ width: "100%", maxWidth: 400 }}>
              <Input
                placeholder="如 510300"
                maxLength={6}
                style={{ flex: 1 }}
                disabled={agentOpBusy}
                onBlur={(e) => {
                  void preheatFundNav(e.target.value);
                }}
              />
              <FundCodeOcrButton
                disabled={agentOpBusy}
                onResolved={(code) => {
                  form.setFieldsValue({ fund_code: code });
                  void preheatFundNav(code);
                }}
              />
            </Space.Compact>
          </Form.Item>
          <Form.Item name="include_fbti" valuePropName="checked">
            <Checkbox disabled={agentOpBusy}>
              纳入 FBTI（使用账户已保存的金融人格参与画像与后续智能体推理）
            </Checkbox>
          </Form.Item>
          <Space wrap>
            <Button
              type="primary"
              loading={loading}
              disabled={simBusy}
              onClick={async () => {
                try {
                  const v = await form.validateFields(["fund_code", "include_fbti"]);
                  await onRun(v as { fund_code: string; include_fbti?: boolean });
                } catch {
                  /* validateFields */
                }
              }}
            >
              运行 MAFB 流水线
            </Button>
            <Button
              icon={<LineChartOutlined />}
              disabled={!/^\d{6}$/.test((watchedFundCode ?? "").trim())}
              onClick={() => void fundNavRef.current?.reload()}
            >
              查询基金净值
            </Button>
            <Button
              icon={<SearchOutlined />}
              loading={simBusy}
              disabled={loading}
              onClick={async () => {
                try {
                  await form.validateFields(["fund_code"]);
                  const c = String(form.getFieldValue("fund_code") ?? "").trim();
                  await runSimilarityLookup(c);
                } catch {
                  /* validateFields */
                }
              }}
            >
              查询相似 TOP10
            </Button>
            <Button loading={probeBusy} disabled={agentOpBusy} onClick={() => void runLlmProbe()}>
              一键探针 Qwen
            </Button>
          </Space>
          {probeResult ? (
            <Alert
              style={{ marginTop: 12 }}
              type={probeResult.ok ? "success" : "warning"}
              showIcon
              message={`探针结果 · model=${String(probeResult.model || "—")} · elapsed=${String(
                probeResult.elapsed_sec ?? "—"
              )}s`}
              description={
                <div style={{ fontSize: 12 }}>
                  <div>
                    status={String(probeResult.status_code ?? "—")} code={String(probeResult.code ?? "—")}
                  </div>
                  <div>message={String(probeResult.message ?? "—")}</div>
                  <div style={{ marginTop: 6, maxHeight: 140, overflow: "auto", whiteSpace: "pre-wrap" }}>
                    raw={String(probeResult.raw ?? "—")}
                  </div>
                </div>
              }
            />
          ) : null}
        </Form>

        <div style={{ marginTop: 22 }}>
          <Typography.Title level={5} style={{ marginBottom: 8, marginTop: 0 }}>
            <LineChartOutlined style={{ marginRight: 8 }} />
            基金净值曲线
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 10, fontSize: 13 }}>
            与上方代码联动；请先点工具栏「查询基金净值」。成功后切换「近一月 / 近三月」等会自动换数据；「更早 / 更晚」平移窗口后也会自动刷新。以 0 开头的代码会按 6 位补零请求东财接口。
          </Typography.Paragraph>
          <FundNavCurvePanel
            ref={fundNavRef}
            embedded
            linkedFundCode={watchedFundCode}
            chartHeight={300}
            hideQueryButton
            onPrimaryLoaded={({ fundCode, preset, points }) => {
              setNavPrimaryStatus(`${fundCode} ${preset} 已就绪 (${points}点)`);
            }}
          />
          {navPrimaryStatus ? (
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              {navPrimaryStatus}
            </Typography.Paragraph>
          ) : null}
        </div>

        {simRefCode ? (
          <div style={{ marginTop: 24 }}>
            <Typography.Title level={5}>相似基金（与上方代码一致：{simRefCode}）</Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
              仅保留多维统计特征余弦（夏普、动量、回撤、风险等级、规模）相似结果；K 线序列相似功能已下线。
            </Typography.Paragraph>
            <Typography.Text strong>统计特征相似（最多 10）</Typography.Text>
            <Table
              size="small"
              style={{ marginTop: 8 }}
              rowKey="code"
              pagination={false}
              dataSource={simFeatureRows}
              locale={{ emptyText: "无数据" }}
              columns={[
                { title: "代码", dataIndex: "code", width: 92 },
                { title: "名称", dataIndex: "name", ellipsis: true },
                { title: "赛道", dataIndex: "track", width: 88 },
                { title: "相似度", dataIndex: "similarity", width: 88 },
                { title: "说明", dataIndex: "rationale", ellipsis: true }
              ]}
            />
          </div>
        ) : null}
      </PageCard>

      <PageCard
        title={catalogMode === "eastmoney_full" ? "基金池（全市场索引）" : "演示基金池"}
        extra={
          fundPanelTab === "catalog" ? (
            <Space.Compact style={{ maxWidth: 360 }}>
              <Input
                allowClear
                placeholder="代码或名称筛选（全库）"
                value={fundSearch}
                disabled={catalogBootstrapLoading || Boolean(catalogInitError)}
                onChange={(e) => setFundSearch(e.target.value)}
                onPressEnter={() => loadFundsSearch()}
              />
              <Button
                type="default"
                loading={fundTableLoading}
                disabled={catalogBootstrapLoading || Boolean(catalogInitError)}
                onClick={() => loadFundsSearch()}
              >
                搜索
              </Button>
            </Space.Compact>
          ) : null
        }
      >
        {catalogInitError ? (
          <Alert
            type="error"
            showIcon
            message="全市场基金目录加载失败"
            description={catalogInitError}
            action={
              <Button
                size="small"
                type="primary"
                onClick={() => {
                  setCatalogInitError(null);
                  setCatalogRetryNonce((n) => n + 1);
                }}
              >
                重试
              </Button>
            }
          />
        ) : (
          <Spin
            spinning={catalogBootstrapLoading || fundTableLoading}
            tip={
              initCatalogMode === "eastmoney_full" && catalogBootstrapLoading
                ? "正在拉取东方财富全市场基金索引（首次约 30–120 秒），其它区域仍可操作…"
                : "加载基金列表…"
            }
          >
            <div style={{ minHeight: 120 }}>
              <Segmented
                style={{ marginBottom: 12 }}
                value={fundPanelTab}
                options={[
                  { label: "搜索 / 分页", value: "catalog" },
                  { label: "随机样本（规则）", value: "random" },
                  { label: "我的自选", value: "my_pool" }
                ]}
                onChange={(v) => {
                  const tab = v as typeof fundPanelTab;
                  setFundPanelTab(tab);
                  if (tab === "catalog") loadCatalogPage(0, fundSearch);
                  else if (tab === "my_pool") loadMyPool();
                  else if (tab === "random") {
                    setFundBundle((prev) =>
                      prev
                        ? {
                            ...prev,
                            items: [],
                            total: 0,
                            view: "random",
                            sample_seed: null,
                            filter_total: null
                          }
                        : null
                    );
                  }
                }}
              />

              {fundPanelTab === "random" ? (
                <Space wrap style={{ marginBottom: 12 }} align="start">
                  <Input
                    style={{ width: 120 }}
                    placeholder="赛道含"
                    value={randTrack}
                    onChange={(e) => setRandTrack(e.target.value)}
                  />
                  <Input
                    style={{ width: 140 }}
                    placeholder="类型含"
                    value={randType}
                    onChange={(e) => setRandType(e.target.value)}
                  />
                  <Checkbox checked={randEtfOnly} onChange={(e) => setRandEtfOnly(e.target.checked)}>
                    仅 ETF
                  </Checkbox>
                  <Space.Compact>
                    <Input
                      style={{ width: 72 }}
                      placeholder="风险≥"
                      maxLength={1}
                      value={randRiskMin}
                      onChange={(e) => setRandRiskMin(e.target.value.replace(/\D/g, "").slice(0, 1))}
                    />
                    <Input
                      style={{ width: 72 }}
                      placeholder="风险≤"
                      maxLength={1}
                      value={randRiskMax}
                      onChange={(e) => setRandRiskMax(e.target.value.replace(/\D/g, "").slice(0, 1))}
                    />
                  </Space.Compact>
                  <Button type="primary" onClick={() => runRandomSample()} disabled={catalogBootstrapLoading}>
                    按规则随机 400 条
                  </Button>
                  <Typography.Text type="secondary">与顶部「搜索」关键词可叠加筛选后再抽样</Typography.Text>
                </Space>
              ) : null}

              {fundPanelTab === "my_pool" ? (
                <Space.Compact style={{ marginBottom: 12, maxWidth: 520 }}>
                  <Input
                    placeholder="多个 6 位代码，逗号/空格分隔"
                    value={poolBulkInput}
                    onChange={(e) => setPoolBulkInput(e.target.value)}
                  />
                  <Button type="primary" onClick={() => void bulkAddPool()}>
                    批量加入自选
                  </Button>
                </Space.Compact>
              ) : null}

              <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
                {fundPanelTab === "random" ? (
                  filterTotal != null ? (
                    <>
                      已在全库中按规则筛出约 <Typography.Text strong>{filterTotal}</Typography.Text>{" "}
                      只候选，本次随机抽取 <Typography.Text strong>{funds.length}</Typography.Text>{" "}
                      条（种子 {String(sampleSeed ?? "—")}）。每次点击都会换一批。
                    </>
                  ) : (
                    <>
                      点击「按规则随机 400 条」从全市场抽样（在候选池中均匀随机，不是固定「前 400」）。可与顶部搜索关键词及下方筛选组合。
                    </>
                  )
                ) : fundPanelTab === "my_pool" ? (
                  <>自选池共 {fundTotal} 条（存数据库，同一账号可见）。</>
                ) : (
                  <>
                    {catalogMode === "eastmoney_full"
                      ? `东方财富公开索引：命中约 ${fundTotal} 只（当前页 ${funds.length ? `${catalogOffset + 1}–${catalogOffset + funds.length}` : "无数据"} 条，可翻页浏览全库）。夏普/回撤等为占位。`
                      : `内置 ${fundTotal} 只演示标的；全市场请设 FUND_CATALOG_MODE=eastmoney_full。`}
                  </>
                )}
              </Typography.Paragraph>
              <Table
                size="small"
                rowKey="code"
                loading={fundTableLoading && !catalogBootstrapLoading}
                pagination={
                  fundPanelTab === "catalog"
                    ? {
                        current: Math.floor(catalogOffset / catalogPageSize) + 1,
                        pageSize: catalogPageSize,
                        total: fundTotal,
                        showSizeChanger: false,
                        onChange: (page) => loadCatalogPage((page - 1) * catalogPageSize, fundSearch)
                      }
                    : { pageSize: 10, total: funds.length, showSizeChanger: false }
                }
                dataSource={funds}
                columns={[
                  { title: "代码", dataIndex: "code", width: 88 },
                  { title: "名称", dataIndex: "name", ellipsis: true },
                  { title: "赛道", dataIndex: "track", width: 100 },
                  { title: "风险", dataIndex: "risk_rating", width: 56 },
                  {
                    title: "操作",
                    key: "op",
                    width: 120,
                    render: (_, row) => (
                      <Space size="small">
                        {fundPanelTab !== "my_pool" ? (
                          <Button type="link" size="small" onClick={() => void addOneToPool(String(row.code))}>
                            自选
                          </Button>
                        ) : null}
                        {fundPanelTab === "my_pool" ? (
                          <Button type="link" size="small" danger onClick={() => void removePoolRow(String(row.code))}>
                            移除
                          </Button>
                        ) : null}
                      </Space>
                    )
                  }
                ]}
              />
            </div>
          </Spin>
        )}
      </PageCard>

      {report && (
        <PageCard title="结构化输出">
          <Space direction="vertical" style={{ width: "100%" }} size="large">
            <div>
              <Tag color={verdict === "pass" ? "green" : "red"}>{verdict === "pass" ? "合规通过" : "合规拦截"}</Tag>
              <Typography.Text> 加权总分：{String(report.weighted_total ?? "-")}</Typography.Text>
            </div>
            <Typography.Title level={5}>各智能体打分</Typography.Title>
            <Descriptions bordered size="small" column={2}>
              {Object.entries(scores).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {v}
                </Descriptions.Item>
              ))}
            </Descriptions>
            <Typography.Title level={5}>加权明细（权重 × 分值）</Typography.Title>
            <Descriptions bordered size="small" column={1}>
              {Object.entries(scoreBreakdown).map(([k, row]) => (
                <Descriptions.Item key={k} label={k}>
                  分 {String((row as { score?: unknown }).score ?? "—")}，权重{" "}
                  {String((row as { weight?: unknown }).weight ?? "—")}
                </Descriptions.Item>
              ))}
            </Descriptions>
            <Typography.Title level={5}>基本面深度可视化（数据源 → 特征 → 推演）</Typography.Title>
            <Card size="small">
              <FundamentalInsightView
                fund={fundData}
                score={typeof scores.fundamental === "number" ? scores.fundamental : undefined}
                reason={agentReasons.fundamental}
                runTrace={runTrace}
              />
            </Card>
            <Typography.Title level={5}>相关舆情（实时抓取）</Typography.Title>
            <Card size="small">
              <NewsSignalView fund={fundData} />
            </Card>
            <Typography.Title level={5}>Risk 新闻辅助贡献（可解释）</Typography.Title>
            <Card size="small">
              <RiskAuxFactorView fund={fundData} />
            </Card>
            <Collapse
              bordered
              items={[
                {
                  key: "reasons",
                  label: "各智能体原始结论（思考过程）",
                  children: (
                    <List
                      size="small"
                      dataSource={Object.entries(agentReasons)}
                      locale={{ emptyText: "暂无分项理由" }}
                      renderItem={([k, text]) => (
                        <List.Item>
                          <Space direction="vertical" size={4} style={{ width: "100%" }}>
                            <Space wrap>
                              <Typography.Text strong>{k}</Typography.Text>
                              {k === "risk" && riskNewsAuxRatio != null ? (
                                <Tag color={riskNewsAuxRatio <= 0.15 ? "green" : riskNewsAuxRatio <= 0.3 ? "gold" : "red"}>
                                  新闻辅助占比 {pct(riskNewsAuxRatio, 1)}
                                </Tag>
                              ) : null}
                            </Space>
                            <Typography.Paragraph style={{ marginBottom: 0 }}>{text}</Typography.Paragraph>
                          </Space>
                        </List.Item>
                      )}
                    />
                  )
                },
                {
                  key: "compliance",
                  label: "合规审查详情",
                  children: complianceBlock ? (
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Typography.Text>
                        is_compliant：{String(complianceBlock.is_compliant ?? "—")}
                      </Typography.Text>
                      {complianceBlock.blocked_reason ? (
                        <Typography.Paragraph type="danger" style={{ marginBottom: 0 }}>
                          {String(complianceBlock.blocked_reason)}
                        </Typography.Paragraph>
                      ) : null}
                      {riskWarningNotes.length ? (
                        <Alert
                          type="warning"
                          showIcon
                          message={`风控告警（${riskWarningNotes.length}）`}
                          description={
                            <List
                              size="small"
                              split={false}
                              dataSource={riskWarningNotes}
                              renderItem={(t) => <List.Item style={{ paddingInline: 0 }}>{t}</List.Item>}
                            />
                          }
                        />
                      ) : null}
                      <List
                        size="small"
                        header="备注"
                        dataSource={commonComplianceNotes}
                        locale={{ emptyText: "暂无其他合规备注" }}
                        renderItem={(t) => <List.Item>{t}</List.Item>}
                      />
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">无</Typography.Text>
                  )
                },
                {
                  key: "rag",
                  label: "RAG 命中片段预览",
                  children: (
                    <List
                      size="small"
                      dataSource={ragChunks}
                      locale={{ emptyText: "无 RAG 片段" }}
                      renderItem={(item) => <List.Item>{clipRagPreview(item)}</List.Item>}
                    />
                  )
                }
              ]}
            />
            <Typography.Title level={5}>用户画像（MAFB：FBTI）</Typography.Title>
            <Card size="small">
              {userProf ? (
                <Space direction="vertical" size="small">
                  <Typography.Text>
                    代码 <Typography.Text code>{String(userProf.fbti_code ?? "—")}</Typography.Text>{" "}
                    {String(userProf.fbti_name ?? "")}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    风险偏好档位：{String(userProf.risk_level ?? "—")}；偏好摘要：
                    {String(userProf.fund_preference_summary ?? "—")}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    标签：{(userProf.style_tags as string[] | undefined)?.join("、") || "—"}
                  </Typography.Text>
                </Space>
              ) : (
                <Typography.Text type="secondary">无</Typography.Text>
              )}
            </Card>
            <Typography.Title level={5}>业绩与风格归因</Typography.Title>
            <Card size="small">
              {(() => {
                const attr = (report.performance_style_attribution as Record<string, unknown> | undefined) || {};
                const src = (attr.attribution_sources as Record<string, unknown> | undefined) || {};
                const sim = (attr.style_similarity as Record<string, unknown> | undefined) || {};
                const dev = (attr.style_deviation as Record<string, unknown> | undefined) || {};
                return (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
                      <Descriptions.Item label="超额收益代理">{pct(attr.excess_return_proxy, 2)}</Descriptions.Item>
                      <Descriptions.Item label="说明">{String(attr.note || "—")}</Descriptions.Item>
                    </Descriptions>
                    <Table
                      size="small"
                      pagination={false}
                      rowKey="k"
                      dataSource={[
                        { k: "选股 Alpha", v: src.stock_selection_alpha },
                        { k: "风格 Beta 溢价", v: src.style_beta_premium },
                        { k: "风格择时", v: src.style_timing },
                        { k: "风险控制", v: src.risk_control }
                      ]}
                      columns={[
                        { title: "收益来源", dataIndex: "k" },
                        { title: "贡献占比", dataIndex: "v", render: (v: unknown) => pct(v, 1) }
                      ]}
                    />
                    <Table
                      size="small"
                      pagination={false}
                      rowKey="k"
                      dataSource={[
                        { k: "大盘", s: sim.large_cap, d: dev.large_cap },
                        { k: "小盘", s: sim.small_cap, d: dev.small_cap },
                        { k: "价值", s: sim.value, d: dev.value },
                        { k: "成长", s: sim.growth, d: dev.growth },
                        { k: "质量", s: sim.quality, d: dev.quality }
                      ]}
                      columns={[
                        { title: "风格维度", dataIndex: "k" },
                        { title: "相似度", dataIndex: "s", render: (v: unknown) => pct(v, 1) },
                        { title: "偏离度", dataIndex: "d", render: (v: unknown) => pct(v, 1) }
                      ]}
                    />
                  </Space>
                );
              })()}
            </Card>
            <Typography.Title level={5}>仓位与风险建议</Typography.Title>
            <Card size="small">
              <PositionAdviceView data={position} />
            </Card>
            <Typography.Title level={5}>可解释推理链（流水线说明）</Typography.Title>
            <List size="small" bordered dataSource={chain} renderItem={(item) => <List.Item>{item}</List.Item>} />
            <Typography.Title level={5}>单基金大模型分析</Typography.Title>
            <Card size="small">
              {singleFundAnalysis ? (
                <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                  {singleFundAnalysis}
                </Typography.Paragraph>
              ) : (
                <Typography.Text type="secondary">暂无单基金分析结论。</Typography.Text>
              )}
            </Card>
            <Typography.Title level={5}>摘要与投教声明</Typography.Title>
            <Card size="small">
              <Typography.Paragraph>{String(report.summary ?? "")}</Typography.Paragraph>
              <Typography.Text type="secondary">{String(report.disclaimer ?? "")}</Typography.Text>
            </Card>
          </Space>
        </PageCard>
      )}
    </div>
  );
}
