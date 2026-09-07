# Edge Functions

Edge Functions 用于服务端 Deno TypeScript 逻辑，如 API 端点、Webhook 处理、第三方集成等需要后端支持的场景。

> **强制：** 业务前端裸 `fetch` / `Taro.request` 只允许调用 `/functions/v1/*`，请求 URL 必须使用平台生成的 `client.ts` 导出的 `supabaseUrl` 拼接。`supabaseUrl` 已是完整的 Supabase 根地址，严禁再追加 `/sb-api` 或自行构造 `/sb-api` 地址；`/sb-api` 仅是历史 Client 的内部代理实现。禁止业务代码直接使用 `VITE_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_URL` / `VITE_ONEDAY_APP_ID` / `EXPO_PUBLIC_ONEDAY_APP_ID`、禁止自行 `createClient()`；也禁止从其他环境变量、硬编码域名或 `window.location.origin` 获取 URL。Database、Auth、Storage、Realtime 仍必须使用平台生成的 `supabase` Client。
> **Client 兼容分支：** 先读取当前 `client.ts`。导出 `projectUrlId` 时，必须导入并携带 `'OneDay-App-Id': projectUrlId`；旧版同源 `/sb-api` Client 未导出该值时，不导入、不携带、不得伪造 App ID；非 `/sb-api` Client 若缺少 `projectUrlId`，必须先通过 Cloud 初始化/关联流程重新生成 Client，禁止继续编写请求。下方示例按新版 Client 展示；仅对旧版 `/sb-api` Client 删除 `projectUrlId` import 和 `OneDay-App-Id` Header，其余保持不变。

## 函数开发流程

1. **编写代码**：在 `/functions/{functionName}/index.ts` 中编写 Deno TypeScript 代码
2. **部署函数**：执行 `meoo-cli cloud deploy-function -n {functionName}` 命令部署函数
3. **重新部署**：每次代码修改后必须重新运行 deploy 命令

## 函数结构

```typescript
Deno.serve(async (req) => {
  const functionName = 'hello-world';
  const requestId = crypto.randomUUID().slice(0, 8);

  const responseHeaders = {
    'Content-Type': 'application/json',
  };

  try {
    const body = await req.json();
    console.info(`[${functionName}] request ${requestId} method=${req.method}`);
    // 业务逻辑
    console.info(`[${functionName}] success ${requestId}`);
    return new Response(JSON.stringify({ data: body }), { headers: responseHeaders });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error(`[${functionName}] failed ${requestId}: ${message}`);
    return new Response(JSON.stringify({ error: message }), {
      status: 400,
      headers: responseHeaders,
    });
  }
});
```

## Deno 编码要求

- Edge Function 运行在 Deno Edge Runtime，使用 `Deno.serve`、Web `Request` / `Response` / `Headers` / `URL` / `fetch`，不要使用 Express、Koa 或 Fastify 风格的 handler。
- 不要启动额外 server、监听端口或创建长生命周期后台进程。
- 不要导入前端 React/Vue/Vite/Next 代码，也不要使用 `fs`、`path`、`child_process`、`http`、`net`、`process` 等 Node-only API，除非 Edge Runtime 文档明确支持。
- `index.ts` 使用的 helper、常量和类型必须已声明，或从当前函数目录内的真实相对路径导入。
- `catch` 中将错误按 `unknown` 处理，使用 `error instanceof Error ? error.message : String(error)`。
- 通过 `Deno.env.get(...)` 读取的必需环境变量要先判空，缺失时返回明确错误。

## 部署前自检

- 确认 `/functions/{functionName}/index.ts` 存在，并且每个被调用的函数、变量和常量都有声明或有效 import。
- 确认 import 路径真实存在且适用于 Deno Edge Runtime，JSON body 属性已做类型校验或收窄，回调参数不会产生隐式 `any`。
- CORS 由 Meoo Cloud 实例域名网关统一校验并生成响应头；函数代码不要重复处理 OPTIONS，也不要设置 `Access-Control-Allow-*` 响应头。
- 如果部署返回 preflight / `deno check` 错误，先按返回的文件、行号和 TypeScript 错误修复代码，不要在代码未修改时重复部署。
- 如果部署返回 `RESOURCE_LIMIT_EXCEEDED` / `function_count_limit`，先执行 `meoo-cli cloud list-functions`，再复用已确认归属当前项目的函数，或清理经确认不再使用的函数，不要重复创建同一个新函数。

## 运行日志写法

写 Edge Function 时可以加少量运行日志，方便用户和 Agent 在调用失败、CORS、第三方 API 报错或线上 500/4xx 时定位问题。日志应记录关键节点和可诊断上下文，但不要刷屏、不要泄露密钥。

**正确做法**：
- 只使用 `console.info` / `console.warn` / `console.error` 表达日志级别，不使用 `console.debug`；日志内容里不要再手写 `[INFO]`、`[DEBUG]`、`[WARN]`、`[ERROR]`，否则日志面板会出现重复级别。
- message 可以保留稳定函数前缀和请求 ID，例如 `[ai-chat] request abc12345 model=qwen3.6-plus messages=2`。
- 推荐记录：请求开始、关键入参摘要（数量/长度/模型名）、上游状态码、耗时、返回错误、流式传输结束或异常。
- 只记录摘要，不记录完整 token、apikey、Authorization、Cookie、service role key、完整请求体、完整用户隐私内容。
- 高频流式日志要节制；如需进度日志，按固定间隔记录摘要（例如每 10 个 chunk 一次），不要每个 chunk 都打。

**示例**：

```typescript
const functionName = 'ai-chat';
const requestId = crypto.randomUUID().slice(0, 8);

console.info(`[${functionName}] request ${requestId} model=${model} messages=${messages.length}`);
console.info(`[${functionName}] upstream ${requestId} status=${response.status} durationMs=${duration}`);

if (!response.ok) {
  const errorBody = await response.text();
  console.error(`[${functionName}] upstream failed ${requestId} status=${response.status}: ${errorBody.slice(0, 300)}`);
}
```

**不要这样写**：

```typescript
console.info(`[ai-chat][INFO] 收到请求 - 模型: ${model}`);
console.error(`[ai-chat][ERROR] SSE 流传输错误: ${message}`);
```

上面会让日志级别重复显示。应改为：

```typescript
console.info(`[ai-chat] 收到请求 - 模型: ${model}`);
console.error(`[ai-chat] SSE 流传输错误: ${message}`);
```

## 环境变量

**系统变量**（始终可用）：
- `SUPABASE_URL` — Supabase API URL（私有网络 URL）
- `SUPABASE_ANON_KEY` — 公共匿名密钥
- `SUPABASE_SERVICE_ROLE_KEY` — 服务角色密钥（保密）
- `SUPABASE_DB_URL` — PostgreSQL 连接 URL
- `MEOO_PROJECT_API_KEY_<projectUrlId>` — 当前项目的 Meoo AI AK，由平台自动注入；Edge Function 根据 `X-Meoo-Project-Url-Id` 请求头优先读取，缺失时可回退旧 `MEOO_PROJECT_API_KEY` 兼容存量项目。该前缀下的变量和旧变量都属于系统保护变量，严禁执行 `set-secret` / `delete-secret`，严禁要求用户填写或提供

**自定义变量**：项目可能配置了额外的密钥。使用 `meoo-cli cloud list-functions` 查看完整的环境变量列表；如需新增或更新变量，使用 `meoo-cli cloud set-secret --name VARIABLE_NAME` 打开配置卡片填写 Secret 值；批量配置可用 `--name A --name B` 或 `--names A,B`。如需删除变量，使用 `meoo-cli cloud delete-secret --name VARIABLE_NAME` 或 `meoo-cli cloud secret delete --names A,B` 打开确认卡片，用户点击确认后执行删除。用户明确提供自己的第三方 API Key 时，必须使用对应的自定义环境变量名（例如百炼使用 `DASHSCOPE_API_KEY`），不得写入或覆盖 `MEOO_PROJECT_API_KEY` 及其项目级变量。不要把 Secret 明文写进命令行、代码或对话。

**重要**：只使用实际存在的环境变量，引用不存在的变量会导致运行时错误。

## Supabase 客户端

```typescript
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

// 管理员客户端（绕过 RLS）
const supabaseAdmin = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
);

// 用户客户端（遵守 RLS，使用前端 Auth header）
const authHeader = req.headers.get('Authorization')!;
const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_ANON_KEY')!,
  { global: { headers: { Authorization: authHeader } } },
);
```

## 前端调用

通过友好的 Toast 交互提醒用户数据操作结果，尤其是失败场景。


用 `fetch` 配合 `supabaseUrl` 调用。如果函数需要用户身份，**必须**手动附加 `Authorization` header；流式响应直接读取 `response.body` 的 ReadableStream。

```typescript
import { projectUrlId, supabase, supabaseUrl } from 'src/supabase/client';

// 获取认证 headers
const session = (await supabase.auth.getSession()).data.session;
const authHeaders = session ? { Authorization: `Bearer ${session.access_token}` } : {};

const response = await fetch(`${supabaseUrl}/functions/v1/hello-world`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'OneDay-App-Id': projectUrlId,
    ...authHeaders,
  },
  body: JSON.stringify({ name: 'world' }),
});

const result = await response.json();
if (!response.ok) {
  console.error('Function error:', result);
}
```






## 部署管理

1. **部署**：`meoo-cli cloud deploy-function -n {functionName}`
2. **删除**：`meoo-cli cloud delete-function -n {functionName}`

> `/functions/{functionName}/` 下的代码修改是本地的，直到再次运行 deploy 命令才会更新在线函数。

## 运行日志诊断

当 Edge Function 调用失败（HTTP 500/4xx、CORS、第三方 API 报错、前端显示接口异常）时，应读取最近运行日志定位根因，然后修改函数代码或配置并重新部署。不要把日志读取当作“确认正常”的健康检查。

1. 从请求 URL `/functions/v1/{functionName}`、前端调用代码或 `meoo-cli cloud list-functions` 确认函数名。
2. 读取最近日志：
   ```bash
   meoo-cli cloud function-logs --name {functionName} --since 15m --limit 20 --json
   ```
   如果日志噪声较多且已知明确关键词，可追加 `--level error` 或 `--grep <keyword>` 二次过滤。
3. 根据日志检查 `/functions/{functionName}/index.ts`、相关环境变量名、CORS/Authorization/apikey 处理和第三方 API 返回。
4. 修复后重新部署：
   ```bash
   meoo-cli cloud deploy-function -n {functionName}
   ```

# 适用场景

- 需要服务器端逻辑（如第三方 API 调用、密钥保护）
- **浏览器真实 CORS 阻止前端 fetch/XHR 调用第三方或不可控外部 API，需要改为受限服务端代理**
- API 端点 / Webhook 处理
- 定时任务 / 后台数据处理
- 需要使用 Service Role Key 绕过 RLS 的操作

### 何时使用 Edge Function 做 CORS 代理

以下场景应使用 Edge Function 做受限服务端代理：
- 预览中确认 CORS 错误来自前端 fetch/XHR 调用第三方或不可控外部 API
- 用户要求 "把这个 API 调用移到后端，避免浏览器 CORS 拦截"
- 用户要求 "用 Edge Function 代理这个外部 API，同时把 API key 留在后端"

**不要** 为以下场景生成代理：
- 静态资源 CDN（图片、字体、CSS）— 低价值，应直接用 `<img>` 或 CSS
- 脚本类 CDN（`cdn.jsdelivr.net`、`unpkg.com`）— 应用 `<script>` 标签加载
- SSE/EventSource 流式请求 — 代理会破坏流式语义
- 目标后端可由用户自行配置 CORS/OPTIONS — 优先指导修目标服务

### CORS 代理安全要求

- 不得实现开放代理，必须限制目标域名、路径范围、HTTP 方法和可转发请求头
- 不要透传所有浏览器 headers/cookies，尤其不要默认转发 Cookie、Authorization、Origin；只转发 allowlist 内必要 headers
- API key、secret、签名或服务端 token 不得留在前端，应放在 Edge Function/环境变量侧；缺少必需环境变量时要 fail fast 返回明确配置错误
- OPTIONS 预检和面向浏览器的 `Access-Control-Allow-*` 响应头由 Meoo Cloud 实例域名网关统一处理，函数只负责受限代理的业务逻辑

## 开发注意事项

1.代码符合 TypeScript 严格模式
- **Error 类型**：`catch (error)` 中 error 是 `unknown` 类型，需要类型检查或断言：
  ```typescript
  catch (error) {
    // 方法1：类型检查
    const message = error instanceof Error ? error.message : 'Unknown error';
    // 方法2：类型断言
    const message = (error as Error).message;
  }
  ```
