/**
 * 将表单/输入中的基金代码规范为 6 位数字字符串。
 * 若值被当成 number 存储，前导 0 会丢失（如 008888 → 8888），东财接口需补零为 "008888"。
 */
export function normalizeSixDigitFundCode(raw: unknown): string | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    const n = Math.trunc(Math.abs(raw));
    if (n < 0 || n > 999999) return null;
    return String(n).padStart(6, "0");
  }
  const digits = String(raw).replace(/\D/g, "").slice(0, 6);
  if (digits.length !== 6) return null;
  return digits;
}
