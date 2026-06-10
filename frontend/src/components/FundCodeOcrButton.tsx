import { ScanOutlined } from "@ant-design/icons";
import { Button, Upload, message } from "antd";
import type { UploadProps } from "antd";
import { useT } from "../hooks/useT";
import { ocrFundCode } from "../services/agent";

type Props = {
  onResolved: (code: string, hint: string) => void;
  disabled?: boolean;
};

/** 在基金代码输入旁：拍照/截图识图，优先 6 位代码，否则按名称在全库反查 */
export function FundCodeOcrButton({ onResolved, disabled }: Props) {
  const { t } = useT();

  const beforeUpload: UploadProps["beforeUpload"] = async (file) => {
    try {
      const data = await ocrFundCode(file);
      const p = data.primary_code;
      if (p && /^\d{6}$/.test(p)) {
        onResolved(p, data.hint);
        message.success(data.hint);
      } else {
        message.warning(data.hint || t("ocr.notFound"));
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("ocr.failed"));
    }
    return false;
  };

  return (
    <Upload showUploadList={false} beforeUpload={beforeUpload} accept="image/*" disabled={disabled}>
      <Button
        type="text"
        size="small"
        icon={<ScanOutlined />}
        aria-label={t("ocr.scanFund")}
        disabled={disabled}
        title={t("ocr.uploadHint")}
      />
    </Upload>
  );
}
