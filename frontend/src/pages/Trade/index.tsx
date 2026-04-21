import { BookOutlined, BulbOutlined, UploadOutlined } from "@ant-design/icons";
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
import type { FormInstance } from "antd/es/form";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageCard } from "../../components/UI/PageCard";
import {
  analyzeTrade,
  createNote,
  createTrade,
  fetchNotes,
  fetchTradeStats,
  fetchTrades,
  importTradeByOcr,
  lookupTradeSecurity,
  searchTradeSecurities
} from "../../services/trade";
import type { SecuritySearchHit } from "../../services/trade";
import { AiAnalysisResult, NoteItem, Trade, TradeStats } from "../../types/trade";
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

const FEE_RATE_OPTIONS = [
  { value: 0.01, label: "万1 (0.01%)" },
  { value: 0.02, label: "万2 (0.02%)" },
  { value: 0.03, label: "万3 (0.03%)" },
  { value: 0.05, label: "万5 (0.05%)" },
  { value: 0.1, label: "千1 (0.1%)" },
  { value: 0.15, label: "千1.5 (0.15%)" },
  { value: 0.25, label: "千2.5 (0.25%)" }
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

function syncBuyLegOnChange(form: FormInstance, changed: Partial<Record<string, unknown>>, all: Record<string, unknown>) {
  const amount = all.buy_amount;
  const feeP = all.fee_percent;
  if (amount == null || feeP == null) return;
  const gross = Number(amount);
  const rate = Number(feeP) / 100;
  const net = gross - gross * rate;
  const price = all.price != null && all.price !== "" ? Number(all.price) : undefined;
  const qty = all.quantity != null && all.quantity !== "" ? Number(all.quantity) : undefined;
  if ("price" in changed && price != null && price > 0) {
    form.setFieldValue("quantity", Number((net / price).toFixed(4)));
  } else if ("quantity" in changed && qty != null && qty > 0) {
    form.setFieldValue("price", Number((net / qty).toFixed(6)));
  } else if (("buy_amount" in changed || "fee_percent" in changed) && price != null && price > 0) {
    form.setFieldValue("quantity", Number((net / price).toFixed(4)));
  } else if (("buy_amount" in changed || "fee_percent" in changed) && qty != null && qty > 0) {
    form.setFieldValue("price", Number((net / qty).toFixed(6)));
  }
}

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
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [openTradeModal, setOpenTradeModal] = useState(false);
  const [tradeForm] = Form.useForm();
  const [secOptions, setSecOptions] = useState<SecuritySearchHit[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [quickNoteForm] = Form.useForm();
  const [saveFromAiForm] = Form.useForm();

  const [selectedTradeId, setSelectedTradeId] = useState<number>();
  const [aiResult, setAiResult] = useState<AiAnalysisResult | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

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
    if (selectedTradeId) {
      quickNoteForm.setFieldValue("trade_id", String(selectedTradeId));
    }
  }, [selectedTradeId, quickNoteForm]);

  const selectedTrade = useMemo(
    () => trades.find((t) => t.id === selectedTradeId),
    [trades, selectedTradeId]
  );

  useEffect(() => {
    setAiResult(null);
  }, [selectedTradeId]);

  const persistNoteView = (mode: NoteViewMode) => {
    setNoteView(mode);
    try {
      localStorage.setItem(NOTE_VIEW_KEY, mode);
    } catch {
      /* ignore */
    }
  };

  const openSaveNoteModal = () => {
    if (!selectedTrade || !aiResult) return;
    const draft = buildDraftNoteFromAnalysis(selectedTrade, aiResult);
    saveFromAiForm.setFieldsValue({ ...draft, trade_id: String(selectedTrade.id) });
    setSaveNoteOpen(true);
  };

  const runAi = async () => {
    if (!selectedTradeId) return;
    setAiLoading(true);
    setAiResult(null);
    try {
      const r = await analyzeTrade(selectedTradeId);
      setAiResult(r);
      message.success("AI 分析完成");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "分析失败");
    } finally {
      setAiLoading(false);
    }
  };

  return (
    <div className="page-stack">
      <Space className="page-actions" wrap>
        <Button type="primary" onClick={() => setOpenTradeModal(true)}>
          新增交易
        </Button>
        <Upload
          showUploadList={false}
          beforeUpload={async (file) => {
            await importTradeByOcr(file);
            message.success("OCR 导入成功");
            await loadAll();
            return false;
          }}
        >
          <Button icon={<UploadOutlined />}>导入交割单</Button>
        </Upload>
      </Space>

      <PageCard title={`交易记录（累计收益 ${currency(stats?.total_profit || 0)}）`}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          点击表格中的一行选中交易，随后在下方进行 AI 分析与笔记记录。
        </Typography.Paragraph>
        <Table<Trade>
          rowKey="id"
          size="middle"
          dataSource={trades}
          pagination={{ pageSize: 8 }}
          rowSelection={{
            type: "radio",
            selectedRowKeys: selectedTradeId ? [selectedTradeId] : [],
            onChange: (keys) => {
              const id = keys[0] as number | undefined;
              setSelectedTradeId(id);
            }
          }}
          onRow={(record) => ({
            onClick: () => setSelectedTradeId(record.id),
            style: { cursor: "pointer" }
          })}
          columns={[
            {
              title: "买卖区间",
              width: 168,
              render: (_: unknown, r: Trade) => {
                if (r.buy_date) {
                  const tail = r.sell_date ? r.sell_date : "持仓";
                  return (
                    <Typography.Text>
                      {r.buy_date} → {tail}
                    </Typography.Text>
                  );
                }
                return r.trade_date;
              }
            },
            { title: "代码", dataIndex: "symbol", width: 88 },
            { title: "名称", dataIndex: "name", ellipsis: true },
            { title: "方向", dataIndex: "direction", width: 72 },
            { title: "买入额", dataIndex: "amount", width: 100, render: (v: number) => currency(v) },
            { title: "盈亏", dataIndex: "profit", width: 100, render: (v: number) => currency(v) },
            { title: "平台", dataIndex: "platform", width: 96, ellipsis: true }
          ]}
        />
      </PageCard>

      <PageCard
        title={
          <Space>
            <BulbOutlined />
            <span>AI 交易分析</span>
          </Space>
        }
      >
        {!selectedTrade ? (
          <Empty description="请先在上方选中一笔交易" />
        ) : (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Typography.Text>
              当前选中：<Typography.Text strong>{selectedTrade.symbol}</Typography.Text>{" "}
              {selectedTrade.name} · {selectedTrade.trade_date} · 盈亏 {currency(selectedTrade.profit)}
            </Typography.Text>
            <Button type="primary" icon={<BulbOutlined />} loading={aiLoading} onClick={() => void runAi()}>
              生成 AI 分析
            </Button>
            {aiLoading ? (
              <Spin tip="正在调用大模型，请稍候…" />
            ) : null}
            {aiResult ? (
              <Card size="small" title="分析结果">
                <Row gutter={[16, 16]}>
                  <Col xs={24} md={8}>
                    <Typography.Title level={5}>优点</Typography.Title>
                    <List
                      size="small"
                      dataSource={aiResult.strengths}
                      renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                    />
                  </Col>
                  <Col xs={24} md={8}>
                    <Typography.Title level={5}>问题</Typography.Title>
                    <List
                      size="small"
                      dataSource={aiResult.problems}
                      renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                    />
                  </Col>
                  <Col xs={24} md={8}>
                    <Typography.Title level={5}>建议</Typography.Title>
                    <List
                      size="small"
                      dataSource={aiResult.suggestions}
                      renderItem={(item) => <List.Item style={{ padding: "4px 0" }}>{item}</List.Item>}
                    />
                  </Col>
                </Row>
                <Button type="default" style={{ marginTop: 12 }} onClick={openSaveNoteModal}>
                  将分析保存为投资笔记
                </Button>
              </Card>
            ) : (
              !aiLoading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成后将在此展示" />
            )}
          </Space>
        )}
      </PageCard>

      <PageCard
        title={
          <Space wrap>
            <BookOutlined />
            <span>投资笔记</span>
            <Segmented
              value={noteView}
              onChange={(v) => persistNoteView(v as NoteViewMode)}
              options={[
                { label: "严谨列表", value: "list" },
                { label: "便签墙", value: "sticky" }
              ]}
            />
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          可手动记录复盘；若已生成 AI 分析，可使用「将分析保存为投资笔记」快速填入。
        </Typography.Paragraph>
        <Form
          form={quickNoteForm}
          layout="vertical"
          onFinish={async (values) => {
            const tid = values.trade_id?.toString().trim();
            await createNote({
              title: values.title,
              content: values.content,
              tags: values.tags || undefined,
              trade_id: tid ? Number(tid) : undefined
            });
            message.success("笔记已保存");
            quickNoteForm.resetFields();
            if (selectedTradeId) {
              quickNoteForm.setFieldsValue({ trade_id: String(selectedTradeId) });
            }
            await loadAll();
          }}
        >
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="标题" name="title" rules={[{ required: true }]}>
                <Input placeholder="例如：本周仓位反思" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="关联交易 ID（可选）" name="trade_id">
                <Input placeholder="留空或与当前选中交易一致" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="标签" name="tags">
                <Input placeholder="趋势, 仓位, 止损" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item label="内容" name="content" rules={[{ required: true }]}>
                <Input.TextArea rows={4} placeholder="记录执行、情绪与改进点…" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit">
            保存笔记
          </Button>
        </Form>

        <Typography.Title level={5} style={{ marginTop: 24 }}>
          我的笔记
        </Typography.Title>

        {noteView === "list" ? (
          <Table<NoteItem>
            rowKey="id"
            size="small"
            pagination={{ pageSize: 6 }}
            dataSource={notes}
            columns={[
              { title: "标题", dataIndex: "title", ellipsis: true },
              {
                title: "关联",
                width: 88,
                render: (_, r) => (r.trade_id ? <Tag>#{r.trade_id}</Tag> : "—")
              },
              { title: "标签", dataIndex: "tags", width: 140, ellipsis: true },
              { title: "内容摘要", dataIndex: "content", ellipsis: true, render: (t: string) => (t || "").slice(0, 80) },
              { title: "时间", dataIndex: "created_at", width: 168 }
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
              <Empty description="暂无便签" />
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
        onCancel={() => {
          setOpenTradeModal(false);
          tradeForm.resetFields();
        }}
        onOk={() => tradeForm.submit()}
        destroyOnClose
      >
        <Form
          form={tradeForm}
          layout="vertical"
          initialValues={{
            buy_date: dayjs(),
            fee_percent: 0.03,
            holding: true,
            platform_preset: "东方财富"
          }}
          onValuesChange={(changed, all) => {
            if ("holding" in changed && changed.holding) {
              tradeForm.setFieldsValue({ sell_date: undefined, sell_amount: undefined });
            }
            syncBuyLegOnChange(tradeForm, changed, all);
          }}
          onFinish={async (values) => {
            const holding = Boolean(values.holding);
            if (!holding) {
              if (!values.sell_date || values.sell_amount == null) {
                message.error("已卖出时请填写卖出日期与卖出成交额");
                return;
              }
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
              fee_percent: Number(values.fee_percent),
              platform,
              notes: values.notes || undefined
            };
            if (values.price != null && values.price !== "") payload.price = Number(values.price);
            if (values.quantity != null && values.quantity !== "") payload.quantity = Number(values.quantity);
            if (!holding) {
              payload.sell_date = (values.sell_date as Dayjs).format("YYYY-MM-DD");
              payload.sell_amount = Number(values.sell_amount);
            }
            await createTrade(payload);
            message.success("交易创建成功");
            setOpenTradeModal(false);
            tradeForm.resetFields();
            await loadAll();
          }}
        >
          <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
            填写买入时间与买入成交额、手续费率（百分比）；再填<strong>买入单价</strong>或<strong>数量</strong>之一即可推算另一项。勾选「仍持仓」表示尚未卖出；否则填写卖出日与卖出成交额，盈亏由服务端计算。
          </Typography.Paragraph>
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="买入日期" name="buy_date" rules={[{ required: true }]}>
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="holding" valuePropName="checked">
                <Checkbox>仍持仓（卖出填「至今」）</Checkbox>
              </Form.Item>
              <Form.Item shouldUpdate noStyle>
                {() =>
                  tradeForm.getFieldValue("holding") ? null : (
                    <Form.Item
                      label="卖出日期"
                      name="sell_date"
                      rules={[{ required: true, message: "请选择卖出日期" }]}
                    >
                      <DatePicker style={{ width: "100%" }} />
                    </Form.Item>
                  )
                }
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
            <Col xs={24} md={8}>
              <Form.Item label="买入成交额（毛）" name="buy_amount" rules={[{ required: true, message: "必填" }]}>
                <InputNumber min={0.01} style={{ width: "100%" }} placeholder="含费前成交金额" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="手续费率" name="fee_percent" rules={[{ required: true }]}>
                <InputNumber min={0} max={100} step={0.01} style={{ width: "100%" }} addonAfter="%" />
              </Form.Item>
              <Select
                placeholder="常用费率"
                options={FEE_RATE_OPTIONS}
                onChange={(v) => tradeForm.setFieldValue("fee_percent", v as number)}
                style={{ width: "100%" }}
                allowClear
              />
            </Col>
            <Col xs={24} md={8}>
              <Form.Item shouldUpdate noStyle>
                {() =>
                  tradeForm.getFieldValue("holding") ? null : (
                    <Form.Item label="卖出成交额（毛）" name="sell_amount" rules={[{ required: true, message: "必填" }]}>
                      <InputNumber min={0.01} style={{ width: "100%" }} />
                    </Form.Item>
                  )
                }
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="买入单价（与数量二选一或都填，以单价优先推算数量）" name="price">
                <InputNumber min={0.0001} style={{ width: "100%" }} placeholder="可空，由数量反推" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="买入数量" name="quantity">
                <InputNumber min={0.0001} style={{ width: "100%" }} placeholder="可空，由单价反推" />
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
            const tid = values.trade_id?.toString().trim();
            await createNote({
              title: values.title,
              content: values.content,
              tags: values.tags || undefined,
              trade_id: tid ? Number(tid) : undefined
            });
            message.success("已保存到投资笔记");
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
          <Form.Item label="关联交易 ID" name="trade_id">
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
