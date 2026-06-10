import type { AppLocale, TranslationDict } from "./types";
import { en } from "./locales/en";
import { zhHK } from "./locales/zh-HK";

const resources: Record<AppLocale, TranslationDict> = {
  "zh-HK": zhHK,
  en
};

export function translate(
  locale: AppLocale,
  key: string,
  params?: Record<string, string | number>
): string {
  const dict = resources[locale] ?? resources["zh-HK"];
  let text = dict[key] ?? resources["zh-HK"][key] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.split(`{{${k}}}`).join(String(v));
    }
  }
  return text;
}

export function getAntdLocaleKey(locale: AppLocale): "zh_HK" | "en_US" {
  return locale === "en" ? "en_US" : "zh_HK";
}

export function getHtmlLang(locale: AppLocale): string {
  return locale === "en" ? "en-HK" : "zh-HK";
}
