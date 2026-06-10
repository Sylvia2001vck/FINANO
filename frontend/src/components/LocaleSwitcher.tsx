import { GlobalOutlined } from "@ant-design/icons";
import { Select } from "antd";
import type { AppLocale } from "../i18n/types";
import { useLocaleStore } from "../store/localeStore";
import { useT } from "../hooks/useT";

const OPTIONS: { value: AppLocale; label: string }[] = [
  { value: "zh-HK", label: "繁體（香港）" },
  { value: "en", label: "English" }
];

export function LocaleSwitcher() {
  const { t } = useT();
  const locale = useLocaleStore((s) => s.locale);
  const setLocale = useLocaleStore((s) => s.setLocale);

  return (
    <Select<AppLocale>
      size="small"
      value={locale}
      onChange={setLocale}
      options={OPTIONS}
      style={{ minWidth: 132 }}
      suffixIcon={<GlobalOutlined />}
      aria-label={t("nav.language")}
    />
  );
}
