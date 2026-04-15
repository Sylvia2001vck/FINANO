import type { CSSProperties, ImgHTMLAttributes } from "react";

const BRAND = {
  /** 白标 + 深色底，适合侧栏深色背景 */
  mark: "/brand/finano-mark-dark-bg.png",
  /** 黑字，适合白底顶栏 / 登录卡片 */
  wordmark: "/brand/finano-wordmark-light-bg.png"
} as const;

export type FinanoLogoVariant = keyof typeof BRAND;

export interface FinanoLogoProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, "src" | "alt"> {
  variant: FinanoLogoVariant;
  /** 像素高度，宽度随比例 */
  height?: number;
}

export function FinanoLogo({ variant, height, style, ...rest }: FinanoLogoProps) {
  const h = height ?? (variant === "mark" ? 40 : 28);
  const merged: CSSProperties = {
    height: h,
    width: "auto",
    maxWidth: "100%",
    objectFit: "contain",
    display: "block",
    ...style
  };
  return <img src={BRAND[variant]} alt="FINANO" height={h} style={merged} {...rest} />;
}
