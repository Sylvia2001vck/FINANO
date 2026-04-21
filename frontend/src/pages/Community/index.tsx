import { Navigate } from "react-router-dom";

/** 已并入「用户与社区」单页 */
export default function CommunityPage() {
  return <Navigate to="/user-community#community" replace />;
}
