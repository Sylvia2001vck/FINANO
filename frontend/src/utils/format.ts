export function currency(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2
  }).format(value || 0);
}

export function percent(value: number) {
  return `${(value || 0).toFixed(2)}%`;
}
