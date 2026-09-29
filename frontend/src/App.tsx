/**
 * The route switch: the student chat, or the admin area.
 *
 * Two screens, so there is no router library and no route table -- `useRoute`
 * reads the hash and this decides. The admin area owns its own sub-routing,
 * because everything under `/admin` needs the same sign-in gate in front of it.
 */
import { AdminApp } from "./pages/admin/AdminApp";
import { Chat } from "./pages/Chat";
import { ADMIN_ROOT, useRoute } from "./lib/router";

export function App() {
  const { path } = useRoute();
  return path === ADMIN_ROOT || path.startsWith(`${ADMIN_ROOT}/`) ? <AdminApp /> : <Chat />;
}
