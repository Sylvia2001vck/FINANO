import { useLocaleStore } from "../store/localeStore";

function numberLocale() {
  const locale = useLocaleStore.getState().locale;
  return locale === "en" ? "en-HK" : "zh-HK";
}

export function currency(value: number) {
  return new Intl.NumberFormat(numberLocale(), {
    style: "currency",
    currency: "HKD",
    maximumFractionDigits: 2
  }).format(value || 0);
}

export function percent(value: number) {
  return `${(value || 0).toFixed(2)}%`;
}
