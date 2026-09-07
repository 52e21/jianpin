// 后端 API 地址：优先取环境变量 VITE_API_BASE_URL（公网 cpolar 地址），
// 本地开发未配置时回退 127.0.0.1:8002。
// 配置方式：在 frontend/.env 写入 VITE_API_BASE_URL=https://xxxx.cpolar.top 后需重启 dev/build。
export const API_BASE: string =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  "http://127.0.0.1:8002";
