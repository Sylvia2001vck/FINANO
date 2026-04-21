import { Navigate } from "react-router-dom";

/** 已并入「用户与社区」单页，保留路由以兼容书签 */
export default function ProfilePage() {
  return <Navigate to="/user-community#profile" replace />;
}
