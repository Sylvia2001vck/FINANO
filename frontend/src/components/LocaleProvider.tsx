import { ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import zhHK from "antd/locale/zh_HK";
import { ReactNode, useEffect } from "react";
import { getAntdLocaleKey, getHtmlLang } from "../i18n";
import { useLocaleStore } from "../store/localeStore";

const antdLocales = {
  zh_HK: zhHK,
  en_US: enUS
} as const;

export function LocaleProvider({ children }: { children: ReactNode }) {
  const locale = useLocaleStore((s) => s.locale);
  const antdKey = getAntdLocaleKey(locale);

  useEffect(() => {
    document.documentElement.lang = getHtmlLang(locale);
  }, [locale]);

  return (
    <ConfigProvider locale={antdLocales[antdKey]}>
      {children}
    </ConfigProvider>
  );
}
