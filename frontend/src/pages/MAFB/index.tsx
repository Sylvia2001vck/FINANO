import { SearchOutlined } from "@ant-design/icons";
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
import { useEffect, useState } from "react";
import { FundCodeOcrButton } from "../../components/FundCodeOcrButton";
import { PageCard } from "../../components/UI/PageCard";
import {
  addMyAgentFunds,
  getFundCatalogStatus,
  listAgentFunds,
  postWarmFundCatalog,
  removeMyAgentFund,
  runMafbStream,
  fetchKlineSimilarFunds,
  fetchSimilarFunds,
  type AgentFundsListResponse,
  type KlineSimilarFundRow,
  type ListAgentFundsParams,
  type SimilarFundRow
} from "../../services/agent";

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
  const [simKlineRows, setSimKlineRows] = useState<KlineSimilarFundRow[]>([]);
  const [simBusy, setSimBusy] = useState(false);

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
      const [feat, kl] = await Promise.all([fetchSimilarFunds(c, 10), fetchKlineSimilarFunds(c, 10, 80)]);
      setSimFeatureRows(feat.similar || []);
      setSimKlineRows(kl.similar || []);
      if (!(feat.similar?.length) && !(kl.similar?.length)) {
        message.info("未得到相似结果（目录或净值数据不足）");
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "查询失败");
      setSimFeatureRows([]);
      setSimKlineRows([]);
    } finally {
      setSimBusy(false);
    }
  };

  const onRun = async (values: { fund_code: string; include_fbti?: boolean }) => {
    setLoading(true);
    setRunStage("正在连接 MAFB 流水线…");
    try {
      const data = await runMafbStream(
        {
          fund_code: values.fund_code.trim(),
          include_fbti: values.include_fbti !== false
        },
        {
          onStage: (_node, label) => {
            setRunStage(`正在执行：${label}`);
          }
        }
      );
      setReport(data.final_report as Record<string, unknown>);
      message.success("MAFB 流水线执行完成");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "执行失败");
    } finally {
      setLoading(false);
      setRunStage(null);
    }
  };

  const scores = (report?.scores as Record<string, number> | undefined) || {};
  const portfolio = (report?.proposed_portfolio as Record<string, unknown>[] | undefined) || [];
  const similarTop5 = (report?.similarity_top5 as Record<string, unknown>[] | undefined) || [];
  const userProf = report?.user_profile as Record<string, unknown> | undefined;
  const chain = (report?.reasoning_chain as string[] | undefined) || [];
  const position = report?.position_advice as Record<string, unknown> | undefined;
  const verdict = report?.verdict as string | undefined;
  const scoreBreakdown = (report?.score_breakdown as Record<string, Record<string, unknown>> | undefined) || {};
  const agentReasons = (report?.reasons as Record<string, string> | undefined) || {};
  const complianceBlock = report?.compliance as Record<string, unknown> | undefined;
  const ragChunks = (report?.rag_chunks as string[] | undefined) || [];

  /** MAFB 与相似查询互斥：避免并行请求导致结果与当前输入错位 */
  const agentOpBusy = loading || simBusy;

  return (
    <div className="page-stack">
      <Typography.Title level={3}>MAFB 多智能体控制台</Typography.Title>
      <Typography.Paragraph type="secondary">
        输入 6 位基金代码后，可运行 MAFB 流水线或查询相似 TOP10（两项不可同时进行，需等当前任务结束）。勾选「纳入 FBTI」时，画像与资产配置会使用账户已保存的金融人格；不勾选则仅用账户风险偏好档位（不含人格偏好摘要）。
        基本面 / 技术面 / 风控 / K 线 / 合规等为 LangGraph 多节点演示。
      </Typography.Paragraph>

      <PageCard title="基金代码与运行">
        {loading && runStage ? (
          <Alert type="info" showIcon style={{ marginBottom: 16 }} message={runStage} />
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
              <Input placeholder="如 510300" maxLength={6} style={{ flex: 1 }} disabled={agentOpBusy} />
              <FundCodeOcrButton
                disabled={agentOpBusy}
                onResolved={(code) => {
                  form.setFieldsValue({ fund_code: code });
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
          </Space>
        </Form>

        {simRefCode ? (
          <div style={{ marginTop: 24 }}>
            <Typography.Title level={5}>相似基金（与上方代码一致：{simRefCode}）</Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
              统计特征余弦与 K 线对齐余弦；全市场模式下候选分层抽样，无足够净值时 K 线使用演示合成序列。
            </Typography.Paragraph>
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
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
              </Col>
              <Col xs={24} lg={12}>
                <Typography.Text strong>K 线序列相似（最多 10）</Typography.Text>
                <Table
                  size="small"
                  style={{ marginTop: 8 }}
                  rowKey="code"
                  pagination={false}
                  dataSource={simKlineRows}
                  locale={{ emptyText: "无数据" }}
                  columns={[
                    { title: "代码", dataIndex: "code", width: 92 },
                    { title: "名称", dataIndex: "name", ellipsis: true },
                    { title: "赛道", dataIndex: "track", width: 88 },
                    { title: "K线相似度", dataIndex: "similarity", width: 96 },
                    { title: "对齐点数", dataIndex: "aligned_points", width: 88 },
                    { title: "净值来源", dataIndex: "nav_series", width: 88 },
                    { title: "说明", dataIndex: "rationale", ellipsis: true }
                  ]}
                />
              </Col>
            </Row>
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
                  分 {(row as { score?: unknown }).score ?? "—"}，权重{" "}
                  {(row as { weight?: unknown }).weight ?? "—"}
                </Descriptions.Item>
              ))}
            </Descriptions>
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
                            <Typography.Text strong>{k}</Typography.Text>
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
                      <List
                        size="small"
                        header="备注"
                        dataSource={(complianceBlock.notes as string[] | undefined) || []}
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
            <Typography.Title level={5}>相似基金 TOP5（K 线序列 + 统计特征余弦）</Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
              与「相似基金」页同源的多维余弦（夏普、动量、回撤、风险等级、规模）并入表；主排序为 K
              线对齐日收益相似度（无足够净值时退化为仅统计相似）。
            </Typography.Paragraph>
            <Table
              size="small"
              rowKey={(row) => String(row.rank ?? row.code)}
              dataSource={similarTop5}
              pagination={false}
              scroll={{ x: "max-content" }}
              columns={[
                { title: "#", dataIndex: "rank", width: 44 },
                { title: "代码", dataIndex: "code", width: 88 },
                { title: "名称", dataIndex: "name", ellipsis: true },
                { title: "赛道", dataIndex: "track", width: 88 },
                {
                  title: "K线相似度",
                  dataIndex: "kline_similarity",
                  render: (v: unknown) => (v == null ? "—" : String(v))
                },
                {
                  title: "统计相似度",
                  dataIndex: "feature_similarity",
                  render: (v: unknown) => (v == null ? "—" : String(v))
                },
                {
                  title: "K线说明",
                  dataIndex: "kline_rationale",
                  ellipsis: true
                },
                {
                  title: "统计说明",
                  dataIndex: "feature_rationale",
                  ellipsis: true
                }
              ]}
            />
            <Typography.Title level={5}>仓位与风险建议</Typography.Title>
            <Card size="small">
              <PositionAdviceView data={position} />
            </Card>
            <Typography.Title level={5}>可解释推理链（流水线说明）</Typography.Title>
            <List size="small" bordered dataSource={chain} renderItem={(item) => <List.Item>{item}</List.Item>} />
            <Typography.Title level={5}>组合草案</Typography.Title>
            <Table
              size="small"
              rowKey={(row) => String(row.code)}
              dataSource={portfolio}
              columns={[
                { title: "代码", dataIndex: "code" },
                { title: "名称", dataIndex: "name" },
                { title: "角色", dataIndex: "role" },
                { title: "权重", dataIndex: "weight" },
                { title: "说明", dataIndex: "rationale" }
              ]}
            />
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
