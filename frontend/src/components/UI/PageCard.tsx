import { Card, CardProps } from "antd";

export function PageCard(props: CardProps) {
  return <Card bordered={false} {...props} />;
}
