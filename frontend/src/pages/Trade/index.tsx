import { BookOutlined, BulbOutlined, DeleteOutlined, UploadOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TradeCurveMarkersChart } from "../../components/Chart/TradeCurveMarkersChart";
import { PageCard } from "../../components/UI/PageCard";
import {
  analyzeReplayByNote,
  analyzeReplayByTrade,
  analyzeTrade,
  createNote,
  deleteTrade,
  createTrade,
  fetchTradeCurve,
  fetchNotes,
  fetchTradeStats,
  fetchTrades,
  importTradeByOcr,
  lookupTradeSecurity,
  searchTradeSecurities
} from "../../services/trade";
import type { SecuritySearchHit } from "../../services/trade";
import { AiAnalysisResult, NoteItem, ReplayAnalysisResult, Trade, TradeCurve, TradeStats } from "../../types/trade";
import { useT } from "../../hooks/useT";
import { currency } from "../../utils/format";

const NOTE_VIEW_KEY = "finano_trade_hub_note_view";

type NoteViewMode = "list" | "sticky";

const STICKY_PALETTES = [
  { bg: "#fff8dc", border: "#e8d48a" },
  { bg: "#e8f4fc", border: "#9ec5e8" },
  { bg: "#f0e8ff", border: "#c4a8e8" },
  { bg: "#e8fff0", border: "#8fd4a8" },
  { bg: "#ffeef5", border: "#f0a8c4" }
];

const PLATFORM_PRESET_OPTIONS = [
  { value: "华泰证券", label: "华泰证券" },
  { value: "东方财富", label: "东方财富" },
  { value: "同花顺", label: "同花顺" },
  { value: "天天基金", label: "天天基金" },
  { value: "雪球", label: "雪球" },
  { value: "支付宝", label: "支付宝" },
  { value: "微信小程序", label: "微信小程序" }
];

function buildDraftNoteFromAnalysis(trade: Trade, ai: AiAnalysisResult) {
  const d = trade.buy_date || trade.trade_date;
  const title = `AI 复盘 · ${trade.symbol} · ${d}`;
  const blocks = [
    "【优点】",
    ...ai.strengths.map((s) => `· ${s}`),
    "",
    "【问题】",
    ...ai.problems.map((s) => `· ${s}`),
    "",
    "【建议】",
    ...ai.suggestions.map((s) => `· ${s}`)
  ];
  return {
    title,
    content: blocks.join("\n"),
    tags: "AI复盘,交易"
  };
}

export default function TradePage() {
  const { t } = useT();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [openTradeModal, setOpenTradeModal] = useState(false);
  const [creatingTrade, setCreatingTrade] = useState(false);
  const [expandedTradeIds, setExpandedTradeIds] = useState<number[]>([]);
  const [curveMap, setCurveMap] = useState<Record<string, TradeCurve | null>>({});
  const [curveLoadingMap, setCurveLoadingMap] = useState<Record<string, boolean>>({});
  const [tradeForm] = Form.useForm();
  const [secOptions, setSecOptions] = useState<SecuritySearchHit[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [quickNoteForm] = Form.useForm();
  const [saveFromAiForm] = Form.useForm();

  const [selectedTradeIds, setSelectedTradeIds] = useState<number[]>([]);
  const [aiResultMap, setAiResultMap] = useState<Record<number, AiAnalysisResult>>({});
  const [analyzedTradeIds, setAnalyzedTradeIds] = useState<number[]>([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayResult, setReplayResult] = useState<ReplayAnalysisResult | null>(null);

  const [noteView, setNoteView] = useState<NoteViewMode>(() => {
    try {
      const v = localStorage.getItem(NOTE_VIEW_KEY);
      return v === "sticky" ? "sticky" : "list";
    } catch {
      return "list";
    }
  });

  const [saveNoteOpen, setSaveNoteOpen] = useState(false);

  const loadAll = useCallback(async () => {
    const [tradeData, summary, noteData] = await Promise.all([fetchTrades(), fetchTradeStats(), fetchNotes()]);
    setTrades(tradeData);
    setStats(summary);
    setNotes(noteData);
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!openTradeModal) return;
    void searchTradeSecurities(" ", 35)
      .then((r) => setSecOptions(r.items))
      .catch(() => setSecOptions([]));
  }, [openTradeModal]);

  useEffect(() => {
    if (selectedTradeIds.length === 1) {
      quickNoteForm.setFieldValue("trade_id", String(selectedTradeIds[0]));
    } else {
      quickNoteForm.setFieldValue("trade_id", undefined);
    }
  }, [selectedTradeIds, quickNoteForm]);

  const selectedTrades = useMemo(
    () => trades.filter((t) => selectedTradeIds.includes(t.id)),
    [trades, selectedTradeIds]
  );
  const selectedTrade = selectedTrades.length === 1 ? selectedTrades[0] : undefined;
  const selectedTradeId = selectedTrade?.id;

  useEffect(() => {
    if (selectedTradeIds.length !== 1) {
      setReplayResult(null);
    }
  }, [selectedTradeIds]);

  /** 当前展开行的标的曲线：交易列表或展开集合变化时重新拉取，避免同代码新增/删除后仍显示旧买卖点 */
  useEffect(() => {
    if (!expandedTradeIds.length) return;

    const symbols = [
      ...new Set(
        expandedTradeIds
          .map((id) => trades.find((t) => t.id === id)?.symbol)
          .filter((s): s is string => Boolean(String(s || "").trim()))
          .map((s) => String(s).trim())
      )
    ];
    if (!symbols.length) return;

    let cancelled = false;

    symbols.forEach((code) => {
      setCurveLoadingMap((m) => ({ ...m, [code]: true }));
    });

    void Promise.all(
      symbols.map(async (code) => {
        try {
          const data = await fetchTradeCurve(code);
          if (!cancelled) setCurveMap((m) => ({ ...m, [code]: data }));
        } catch {
          if (!cancelled) setCurveMap((m) => ({ ...m, [code]: null }));
        } finally {
          if (!cancelled) setCurveLoadingMap((m) => ({ ...m, [code]: false }));
        }
      })
    );

    return () => {
      cancelled = true;
    };
  }, [trades, expandedTradeIds]);

  const persistNoteView = (mode: NoteViewMode) => {
    setNoteView(mode);
    try {
      localStorage.setItem(NOTE_VIEW_KEY, mode);
    } catch {
      /* ignore */
    }
  };

  const openSaveNoteModal = () => {
    if (!selectedTrade) return;
    const ai = aiResultMap[selectedTrade.id];
    if (!ai) return;
    const draft = buildDraftNoteFromAnalysis(selectedTrade, ai);
    saveFromAiForm.setFieldsValue({ ...draft, trade_id: String(selectedTrade.id) });
    setSaveNoteOpen(true);
  };

  const resolveLinkedTradeId = (rawTradeId: unknown): number | undefined => {
    if (selectedTradeId != null) return selectedTradeId;
    const tid = String(rawTradeId ?? "").trim();
    if (!tid) return undefined;
    const n = Number(tid);
    return Number.isFinite(n) ? n : undefined;
  };

  const buildReplayFooter = (replay: ReplayAnalysisResult) => {
    if (replay.has_match && replay.matched_notes.length > 0) {
      const top = replay.matched_notes[0];
      const relation = top.trade_id
        ? `，关联交易 #${top.trade_id}${top.trade_symbol ? `（${top.trade_symbol}）` : ""}`
        : "";
      return [
        "【AI关联回顾】",
        `你在历史笔记 #${top.note_id}${relation} 里也记录过相似情绪（相似度 ${top.similarity.toFixed(2)}）。`,
        replay.analysis
      ].join("\n");
    }
    return [
      "【AI复盘补充】",
      replay.analysis,
      ...(replay.suggestions || []).slice(0, 3).map((s) => `- ${s}`)
    ].join("\n");
  };

  const enrichNoteContentWithReplay = async (title: string, content: string) => {
    try {
      const replay = await analyzeReplayByNote({ title, content });
      return `${content}\n\n---\n${buildReplayFooter(replay)}`;
    } catch {
      return content;
    }
  };

  const runAi = async () => {
    if (!selectedTradeIds.length) {
      message.warning(t("trade.selectOneTrade"));
      return;
    }
    setAiLoading(true);
    setReplayLoading(selectedTradeIds.length === 1);
    setReplayResult(null);
    try {
      const ids = [...selectedTradeIds];
      const aiPairs = await Promise.all(ids.map(async (id) => ({ id, ai: await analyzeTrade(id) })));
      setAiResultMap((prev) => {
        const next = { ...prev };
        for (const pair of aiPairs) next[pair.id] = pair.ai;
        return next;
      });
      setAnalyzedTradeIds(ids);
      if (ids.length === 1) {
        const replay = await analyzeReplayByTrade(ids[0]);
        setReplayResult(replay);
        message.success(t("trade.aiSingleDone"));
      } else {
        setReplayResult(null);
        message.success(t("trade.aiBatchDone", { count: ids.length }));
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("trade.aiFailed"));
    } finally {
      setAiLoading(false);
      setReplayLoading(false);
    }
  };

  return (
    <div className="page-stack">
      <Space className="page-actions" wrap>
        <Button type="primary" onClick={() => setOpenTradeModal(true)}>
          {t("trade.addTrade")}
        </Button>
        <Upload
          showUploadList={false}
          beforeUpload={async (file) => {
            await importTradeByOcr(file);
            message.success(t("trade.ocrImportOk"));
            await loadAll();
            return false;
          }}
        >
          <Button icon={<UploadOutlined />}>{t("trade.importOcr")}</Button>
        </Upload>
      </Space>

      <PageCard title={t("trade.recordsTitle", { profit: currency(stats?.total_profit || 0) })}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          {t("trade.multiSelectHint")}
        </Typography.Paragraph>
        <Space style={{ marginBottom: 12 }}>
          <Button size="small" onClick={() => setSelectedTradeIds(trades.map((tr) => tr.id))}>
            {t("trade.selectAll")}
          </Button>
          <Button size="small" onClick={() => setSelectedTradeIds([])}>
            {t("trade.clearSelection")}
          </Button>
        </Space>
        <Table<Trade>
          rowKey="id"
          size="middle"
          dataSource={trades}
          pagination={{ pageSize: 8 }}
          expandable={{
            expandedRowKeys: expandedTradeIds,
            rowExpandable: (record) => Boolean(record.symbol),
            onExpand: (expanded, record) => {
              setExpandedTradeIds((keys) => {
                if (expanded) return keys.includes(record.id) ? keys : [...keys, record.id];
                return keys.filter((k) => k !== record.id);
              });
            },
            expandedRowRender: (record) => (
              <div>
                <Typography.Text type="secondary">{t("trade.curveHint")}</Typography.Text>
                <TradeCurveMarkersChart
                  curve={curveMap[record.symbol]}
                  loading={Boolean(curveLoadingMap[record.symbol])}
                  height={280}
                />
              </div>
            )
          }}
          rowSelection={{
            selectedRowKeys: selectedTradeIds,
            onChange: (keys) => {
              setSelectedTradeIds(keys.map((k) => Number(k)).filter((k) => Number.isFinite(k)));
            }
          }}
          onRow={(record) => ({
            onClick: () =>
              setSelectedTradeIds((prev) =>
                prev.includes(record.id) ? prev.filter((id) => id !== record.id) : [...prev, record.id]
              ),
            style: { cursor: "pointer" }
          })}
          columns={[
            {
              title: t("trade.period"),
              width: 168,
              render: (_: unknown, r: Trade) => {
                if (r.buy_date) {
                  const tail = r.sell_date ? r.sell_date : t("common.holding");
                  return (
                    <Typography.Text>
                      {r.buy_date} → {tail}
                    </Typography.Text>
                  );
                }
                return r.trade_date;
              }
            },
            { title: t("common.code"), dataIndex: "symbol", width: 88 },
            { title: t("common.name"), dataIndex: "name", ellipsis: true },
            { title: t("trade.direction"), dataIndex: "direction", width: 72 },
            { title: t("trade.buyAmount"), dataIndex: "amount", width: 100, render: (v: number) => currency(v) },
            { title: t("trade.pnl"), dataIndex: "profit", width: 100, render: (v: number) => currency(v) },
            { title: t("trade.platform"), dataIndex: "platform", width: 96, ellipsis: true },
            {
              title: t("common.action"),
              width: 90,
              render: (_: unknown, r: Trade) => (
                <Popconfirm
                  title={t("trade.confirmDelete")}
                  okText={t("common.delete")}
                  cancelText={t("common.cancel")}
                  okButtonProps={{ danger: true }}
                  onConfirm={async () => {
                    await deleteTrade(r.id);
                    setSelectedTradeIds((ids) => ids.filter((id) => id !== r.id));
                    setAnalyzedTradeIds((ids) => ids.filter((id) => id !== r.id));
                    setAiResultMap((m) => {
                      const next = { ...m };
                      delete next[r.id];
                      return next;
                    });
                    message.success(t("trade.deleted"));
                    await loadAll();
                  }}
                >
                  <Button type="link" danger size="small" icon={<DeleteOutlined />}>
                    {t("common.delete")}
                  </Button>
                </Popconfirm>
              )
            }
          ]}
        />
      </PageCard>

      <PageCard
        title={
          <Space>
            <BulbOutlined />
            <span>{t("trade.aiAnalysis")}</span>
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          {selectedTrades.length ? (
            <Typography.Text>
              当前已选 <Typography.Text strong>{selectedTrades.length}</Typography.Text> 笔
              {selectedTrade
                ? `（单笔：${selectedTrade.symbol} ${selectedTrade.name} · ${selectedTrade.trade_date} · 盈亏 ${currency(selectedTrade.profit)}）`
                : "（多笔/全选模式）"}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">{t("trade.selectFirst")}</Typography.Text>
          )}
          <Button type="primary" icon={<BulbOutlined />} loading={aiLoading || replayLoading} onClick={() => void runAi()}>
            {t("trade.runAi")}
          </Button>
          {aiLoading ? <Spin tip={t("trade.aiRunning")} /> : null}
          {replayLoading ? <Spin tip={t("trade.replayRunning")} /> : null}
          {analyzedTradeIds.length ? (
            <Space direction="vertical" style={{ width: "100%" }}>
              {analyzedTradeIds
                .map((id) => {
                  const trade = trades.find((t) => t.id === id);
                  const ai = aiResultMap[id];
                  if (!trade || !ai) return null;
                  return { id, trade, ai };
                })
                .filter((x): x is { id: number; trade: Trade; ai: AiAnalysisResult } => Boolean(x))
                .map(({ id, trade, ai }) => (
                  <Card
                    key={id}
                    size="small"
                    title={`#${id} ${trade.symbol} ${trade.name} · ${currency(trade.profit)}`}
                  >
                    <Row gutter={[16, 16]}>
                      <Col xs={24} md={8}>
                        <Typography.Title level={5}>{t("trade.strengths")}</Typography.Title>
                        <List
                          size="small"
                          dataSource={ai.strengths}
                          renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                        />
                      </Col>
                      <Col xs={24} md={8}>
                        <Typography.Title level={5}>{t("trade.problems")}</Typography.Title>
                        <List
                          size="small"
                          dataSource={ai.problems}
                          renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                        />
                      </Col>
                      <Col xs={24} md={8}>
                        <Typography.Title level={5}>{t("trade.suggestions")}</Typography.Title>
                        <List
                          size="small"
                          dataSource={ai.suggestions}
                          renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                        />
                      </Col>
                    </Row>
                    {selectedTradeId === id ? (
                      <Button type="default" style={{ marginTop: 12 }} onClick={openSaveNoteModal}>
                        {t("trade.saveAsNote")}
                      </Button>
                    ) : null}
                  </Card>
                ))}
            </Space>
          ) : (
            !aiLoading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("trade.showAfterGenerate")} />
          )}
          {replayResult ? (
            <Card
              size="small"
              title={
                <Space wrap>
                  <span>{t("trade.similarMoments")}</span>
                  <Tag color={replayResult.route === "history_compare" ? "green" : "default"}>
                    {replayResult.route === "history_compare" ? t("trade.historyBranch") : t("trade.nativeBranch")}
                  </Tag>
                  <Tag>source={replayResult.retrieval_source}</Tag>
                  <Tag>score={replayResult.top_score.toFixed(3)}</Tag>
                  <Tag>threshold={replayResult.similarity_threshold.toFixed(2)}</Tag>
                </Space>
              }
            >
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{replayResult.analysis}</Typography.Paragraph>
              {replayResult.suggestions.length ? (
                <>
                  <Typography.Title level={5}>建议</Typography.Title>
                  <List
                    size="small"
                    dataSource={replayResult.suggestions}
                    renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                  />
                </>
              ) : null}
              {replayResult.matched_trades.length ? (
                <>
                  <Typography.Title level={5}>{t("trade.matchedTrades")}</Typography.Title>
                  <List
                    size="small"
                    dataSource={replayResult.matched_trades}
                    renderItem={(item) => (
                      <List.Item style={{ display: "block", padding: "8px 0" }}>
                        <Typography.Text strong>
                          #{item.trade_id} {item.symbol} {item.name}
                        </Typography.Text>
                        <div>
                          相似度 {item.similarity.toFixed(3)} · 金额 {currency(item.amount)} · 盈亏 {currency(item.profit)}
                        </div>
                        {(item.notes || []).map((n, idx) => (
                          <div key={`${item.trade_id}-${idx}`} style={{ color: "#666" }}>
                            - {n}
                          </div>
                        ))}
                      </List.Item>
                    )}
                  />
                </>
              ) : null}
            </Card>
          ) : null}
        </Space>
      </PageCard>

      <PageCard
        title={
          <Space wrap>
            <BookOutlined />
            <span>{t("trade.notes")}</span>
            <Segmented
              value={noteView}
              onChange={(v) => persistNoteView(v as NoteViewMode)}
              options={[
                { label: t("trade.listView"), value: "list" },
                { label: t("trade.stickyView"), value: "sticky" }
              ]}
            />
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          {t("trade.notesHint")}
        </Typography.Paragraph>
        <Form
          form={quickNoteForm}
          layout="vertical"
          onFinish={async (values) => {
            const tid = values.trade_id?.toString().trim();
            const rawContent = String(values.content || "");
            const enrichedContent = await enrichNoteContentWithReplay(String(values.title || ""), rawContent);
            await createNote({
              title: values.title,
              content: enrichedContent,
              tags: values.tags || undefined,
              trade_id: tid ? Number(tid) : undefined
            });
            message.success(t("trade.noteSaved"));
            quickNoteForm.resetFields();
            if (selectedTradeId != null) {
              quickNoteForm.setFieldsValue({ trade_id: String(selectedTradeId) });
            }
            await loadAll();
          }}
        >
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label={t("trade.noteTitle")} name="title" rules={[{ required: true }]}>
                <Input placeholder={t("trade.noteTitlePh")} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label={t("trade.noteTradeId")} name="trade_id">
                <Input placeholder={t("trade.noteTradeIdPh")} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label={t("trade.noteTags")} name="tags">
                <Input placeholder={t("trade.noteTagsPh")} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item label={t("trade.noteContent")} name="content" rules={[{ required: true }]}>
                <Input.TextArea rows={4} placeholder={t("trade.noteContentPh")} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit">
            {t("trade.saveNote")}
          </Button>
        </Form>

        <Typography.Title level={5} style={{ marginTop: 24 }}>
          {t("trade.myNotes")}
        </Typography.Title>

        {noteView === "list" ? (
          <Table<NoteItem>
            rowKey="id"
            size="small"
            pagination={{ pageSize: 6 }}
            dataSource={notes}
            columns={[
              { title: t("trade.noteTitle"), dataIndex: "title", ellipsis: true },
              {
                title: t("trade.link"),
                width: 88,
                render: (_, r) => (r.trade_id ? <Tag>#{r.trade_id}</Tag> : "—")
              },
              { title: t("trade.noteTags"), dataIndex: "tags", width: 140, ellipsis: true },
              { title: t("trade.summary"), dataIndex: "content", ellipsis: true, render: (txt: string) => (txt || "").slice(0, 80) },
              { title: t("trade.time"), dataIndex: "created_at", width: 168 }
            ]}
          />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 20,
              padding: "8px 4px 24px"
            }}
          >
            {notes.length === 0 ? (
              <Empty description={t("trade.noSticky")} />
            ) : (
              notes.map((n) => {
                const pal = STICKY_PALETTES[Math.abs(n.id) % STICKY_PALETTES.length];
                const rot = ((n.id % 7) - 3) * 0.6;
                return (
                  <div
                    key={n.id}
                    style={{
                      background: pal.bg,
                      border: `1px solid ${pal.border}`,
                      borderRadius: 3,
                      padding: "14px 14px 18px",
                      boxShadow: "4px 5px 14px rgba(0,0,0,0.12)",
                      transform: `rotate(${rot}deg)`,
                      transition: "transform 0.2s ease",
                      minHeight: 140,
                      position: "relative"
                    }}
                  >
                    <div
                      style={{
                        position: "absolute",
                        top: 0,
                        left: "50%",
                        transform: "translateX(-50%)",
                        width: 48,
                        height: 10,
                        background: "rgba(0,0,0,0.06)",
                        borderRadius: "0 0 4px 4px"
                      }}
                      aria-hidden
                    />
                    <Typography.Text strong style={{ fontSize: 15, display: "block", marginBottom: 8 }}>
                      {n.title}
                    </Typography.Text>
                    {n.trade_id ? (
                      <Tag style={{ marginBottom: 8 }}>交易 #{n.trade_id}</Tag>
                    ) : null}
                    {n.tags ? (
                      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                        {n.tags}
                      </Typography.Paragraph>
                    ) : null}
                    <Typography.Paragraph
                      style={{
                        margin: 0,
                        whiteSpace: "pre-wrap",
                        fontSize: 13,
                        lineHeight: 1.55,
                        display: "-webkit-box",
                        WebkitLineClamp: 8,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden"
                      }}
                    >
                      {n.content}
                    </Typography.Paragraph>
                    <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 10, display: "block" }}>
                      {n.created_at}
                    </Typography.Text>
                  </div>
                );
              })
            )}
          </div>
        )}
      </PageCard>

      <Modal
        title="新增交易 / 持仓"
        open={openTradeModal}
        width={720}
        confirmLoading={creatingTrade}
        okButtonProps={{ disabled: creatingTrade }}
        cancelButtonProps={{ disabled: creatingTrade }}
        onCancel={() => {
          if (creatingTrade) return;
          setOpenTradeModal(false);
          tradeForm.resetFields();
        }}
        onOk={() => {
          if (creatingTrade) return;
          tradeForm.submit();
        }}
        destroyOnClose
      >
        <Form
          form={tradeForm}
          layout="vertical"
          initialValues={{
            buy_date: dayjs(),
            holding: true,
            platform_preset: "东方财富"
          }}
          onValuesChange={(changed, all) => {
            if ("holding" in changed && changed.holding) {
              tradeForm.setFieldsValue({ sell_date: undefined, sell_amount: undefined });
            }
          }}
          onFinish={async (values) => {
            if (creatingTrade) return;
            const holding = Boolean(values.holding);
            if (!holding && !values.sell_date) {
              message.error("已卖出时请填写卖出日期");
              return;
            }
            const platform =
              (values.platform_custom && String(values.platform_custom).trim()) ||
              (values.platform_preset && String(values.platform_preset).trim()) ||
              "manual";
            const payload: Record<string, unknown> = {
              symbol: String(values.symbol).trim(),
              name: String(values.name).trim(),
              buy_date: (values.buy_date as Dayjs).format("YYYY-MM-DD"),
              amount: Number(values.buy_amount),
              platform,
              notes: values.notes || undefined
            };
            if (!holding) {
              payload.sell_date = (values.sell_date as Dayjs).format("YYYY-MM-DD");
            }
            setCreatingTrade(true);
            try {
              const created = await createTrade(payload);
              if (created?.dedup_hit) {
                message.info("检测到重复提交，已自动去重");
              } else {
                message.success("交易创建成功");
              }
              setOpenTradeModal(false);
              tradeForm.resetFields();
              await loadAll();
            } finally {
              setCreatingTrade(false);
            }
          }}
        >
          <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
            只需填写买入成交额。系统会根据基金代码与买入日期自动从天天基金历史净值反查买入单价并逆向计算买入数量。勾选「仍持仓」表示尚未卖出；否则只需填写卖出日期，系统会按卖出日净值自动估算卖出额并计算盈亏（暂不计手续费）。
          </Typography.Paragraph>
          <Row gutter={12}>
            <Col xs={24} md={10}>
              <Form.Item label="买入日期" name="buy_date" rules={[{ required: true }]}>
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={4}>
              <Form.Item label=" " colon={false} name="holding" valuePropName="checked">
                <Checkbox>仍持仓（卖出填「至今」）</Checkbox>
              </Form.Item>
            </Col>
            <Col xs={24} md={10}>
              <Form.Item shouldUpdate noStyle>
                {() => (
                  <Form.Item
                    label="卖出日期"
                    name="sell_date"
                    rules={[
                      ({ getFieldValue }) => ({
                        validator(_, value) {
                          if (getFieldValue("holding")) return Promise.resolve();
                          if (value) return Promise.resolve();
                          return Promise.reject(new Error("请选择卖出日期"));
                        }
                      })
                    ]}
                  >
                    <DatePicker style={{ width: "100%" }} disabled={Boolean(tradeForm.getFieldValue("holding"))} />
                  </Form.Item>
                )}
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="从基金库搜索（名称或代码）">
            <Select
              showSearch
              allowClear
              placeholder="输入关键字，下拉选取"
              filterOption={false}
              options={secOptions.map((s) => ({ value: s.code, label: `${s.code} ${s.name}` }))}
              onSearch={(q) => {
                if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
                searchTimerRef.current = setTimeout(() => {
                  void searchTradeSecurities(q.trim() || " ", 40)
                    .then((r) => setSecOptions(r.items))
                    .catch(() => setSecOptions([]));
                }, 280);
              }}
              onChange={(code) => {
                if (!code) return;
                const hit = secOptions.find((x) => x.code === code);
                if (hit) tradeForm.setFieldsValue({ symbol: hit.code, name: hit.name });
              }}
            />
          </Form.Item>
          <Row gutter={12}>
            <Col xs={24} md={8}>
              <Form.Item
                label="证券代码"
                name="symbol"
                rules={[
                  { required: true, message: "请输入代码" },
                  { pattern: /^\d{6}$/, message: "须为 6 位数字代码" }
                ]}
              >
                <Input
                  maxLength={6}
                  placeholder="510300"
                  onBlur={async (e) => {
                    const v = e.target.value.trim();
                    if (!/^\d{6}$/.test(v)) return;
                    try {
                      const hit = await lookupTradeSecurity(v);
                      tradeForm.setFieldsValue({ name: hit.name });
                    } catch {
                      /* 未命中则保留手输名称 */
                    }
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item label="证券名称" name="name" rules={[{ required: true, message: "请输入或搜索名称" }]}>
                <Input placeholder="与代码对应，可手改" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="买入成交额" name="buy_amount" rules={[{ required: true, message: "必填" }]}>
                <InputNumber min={0.01} style={{ width: "100%" }} placeholder="仅需输入成交总额" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="交易平台（常用）" name="platform_preset">
                <Select allowClear placeholder="选常用或下方手输" options={PLATFORM_PRESET_OPTIONS} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="平台（手输，优先于下拉）" name="platform_custom">
                <Input placeholder="覆盖下拉；都空则记为 manual" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="备注" name="notes">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="保存为投资笔记"
        open={saveNoteOpen}
        onCancel={() => {
          setSaveNoteOpen(false);
          saveFromAiForm.resetFields();
        }}
        okText="保存到笔记"
        onOk={async () => {
          try {
            const values = await saveFromAiForm.validateFields();
            const rawContent = String(values.content || "");
            const enrichedContent = await enrichNoteContentWithReplay(String(values.title || ""), rawContent);
            await createNote({
              title: values.title,
              content: enrichedContent,
              tags: values.tags || undefined,
              trade_id: resolveLinkedTradeId(values.trade_id)
            });
            message.success("已保存到投资笔记（含历史相似关联）");
            setSaveNoteOpen(false);
            saveFromAiForm.resetFields();
            await loadAll();
          } catch {
            /* validate failed */
          }
        }}
        destroyOnClose
        width={560}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          可修改标题与正文后再保存；将写入下方「我的笔记」。
        </Typography.Paragraph>
        <Form form={saveFromAiForm} layout="vertical" preserve={false}>
          <Form.Item label="标题" name="title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="关联交易">
            <Typography.Text>{selectedTradeId ? `自动关联 #${selectedTradeId}` : "非单笔选择（将按草稿值回退）"}</Typography.Text>
          </Form.Item>
          <Form.Item name="trade_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item label="标签" name="tags">
            <Input />
          </Form.Item>
          <Form.Item label="内容" name="content" rules={[{ required: true }]}>
            <Input.TextArea rows={10} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
