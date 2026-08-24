/** Router-Guards für geschützte Routen, Ersatz für RequireAuth.tsx bzw. den
 * Inline-Check in TemplateAdminPage.tsx. */
import { PENDING, type Guard } from "../lib/router.js";
import { getState } from "./authStore.js";

export function requireAuth(): Guard {
  return () => {
    const { user, loading } = getState();
    if (loading) return PENDING;
    if (!user) return `/login?from=${encodeURIComponent(location.pathname)}`;
    return true;
  };
}

export function requireAdmin(): Guard {
  const auth = requireAuth();
  return (ctx) => {
    const authResult = auth(ctx);
    if (authResult !== true) return authResult;
    const { user } = getState();
    if (user?.role !== "admin") return "/";
    return true;
  };
}
