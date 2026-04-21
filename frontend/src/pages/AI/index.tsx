import { Navigate } from "react-router-dom";

/** 已并入「交易与复盘」`/trade`，保留路由以兼容书签。 */
export default function AIPage() {
  return <Navigate to="/trade" replace />;
}
