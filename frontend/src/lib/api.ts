// 后端 API 地址：优先取环境变量 VITE_API_BASE_URL（公网 cpolar 地址），
// 本地开发未配置时回退 127.0.0.1:8002。
// 配置方式：在 frontend/.env 写入 VITE_API_BASE_URL=https://xxxx.cpolar.top 后需重启 dev/build。
export const API_BASE: string =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  "http://127.0.0.1:8002";

const SESSION_ID_KEY = "jianpin_session_id";

/**
 * 第 9 步：后端缓存已按 (tenant_id, session_id, JD, 简历) 隔离。
 * 当前项目没有登录体系，tenant_id 固定 "default"；session_id 每个浏览器会话生成一次并复用，
 * 接入账号体系后把 tenant_id 换成真实租户即可。
 */
export function getSessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_ID_KEY);
    if (existing) return existing;
    const id = `s_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    sessionStorage.setItem(SESSION_ID_KEY, id);
    return id;
  } catch {
    return "default";
  }
}
