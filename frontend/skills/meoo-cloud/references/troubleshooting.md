# 问题排查

## CLI 命令问题

### 命令执行规则
1. **独立执行**：每个 CLI 命令必须单独调用，等待结果后再继续
2. **确认等待**：启用云服务时会弹出确认卡片，必须等待用户确认完成

### Cloud 环境变量或 `.env` 丢失

出现 `Missing environment variable: VITE_ONEDAY_APP_ID`、缺少 `VITE_SUPABASE_*` / `EXPO_PUBLIC_SUPABASE_*`，或者 `.env` / `.env.miniprogram` 不存在时，不要手工创建文件、复制旧值或修改 `src/supabase/client.ts`。直接执行：

```bash
meoo-cli cloud regenerate-env
```

该命令只在当前项目已开通 Cloud 时生效，并根据当前 Cloud 绑定重新生成平台托管环境文件。成功后单独执行 `pnpm run dev`，让前端重新加载变量。

## 数据库问题

### SQL HTTP 400
这是 PostgreSQL 已拒绝 SQL，禁止原样重试：
1. 重新运行 `meoo-cli cloud tables` 获取真实 schema
2. 按错误中的 table/column/constraint/type 定位问题
3. 修正 SQL 后再执行；不要通过重复提交碰运气

常见对应关系：`column/relation does not exist` 检查命名；`not-null/foreign key/check/unique` 检查约束与数据；`operator does not exist` 检查 UUID/text/enum 类型；`already exists` 把迁移改为幂等写法。

### query/migrate HTTP 502
写操作或 DDL 是否已执行可能不确定，禁止自动原样重放。先运行 `cloud tables`，必要时用只读 query 检查目标对象/数据是否已生效；确认未生效后再由 Agent 生成安全的幂等修复 SQL。

### 数据看不到
通常是 RLS 策略与实际功能不匹配：
- 如果应用没有登录功能，使用匿名友好策略：`USING (true)`
- 如果应用有登录功能，确保策略正确使用 `auth.uid()`

### RLS 违规错误
插入数据时出现"违反行级安全"：
- 确保 `user_id` 字段在 INSERT 时正确设置为 `auth.uid()`
- 确保 `user_id` 字段不是 nullable（如果 RLS 策略依赖它）

### 写操作"成功"但数据没写入
RLS 拦截 INSERT/UPDATE/DELETE 时，`error` 为 `null`、仅返回空数组，前端容易误判为成功。写操作必须 `.insert(...).select()`，data 长度为 0 视为失败并检查 RLS 策略（详见 `database.md` 的"写操作必须校验影响行数"）。

### 无限递归错误
RLS 策略直接引用同一表：
```sql
-- ❌ 会导致无限递归
CREATE POLICY "example" ON profiles
FOR SELECT USING ((SELECT role FROM profiles WHERE id = auth.uid()) = 'admin');

-- ✅ 使用安全定义函数
CREATE POLICY "example" ON profiles
FOR SELECT USING (public.has_role(auth.uid(), 'admin'));
```

## 认证问题

### 认证状态监听死锁
```typescript
-- ❌ 错误：会导致死锁
supabase.auth.onAuthStateChange(async (event, session) => {
  const profile = await supabase.from('profiles').select()... // 死锁
});

-- ✅ 正确：延迟 Supabase 调用
supabase.auth.onAuthStateChange((event, session) => {
  setSession(session);
  if (session?.user) {
    setTimeout(() => fetchUserProfile(session.user.id), 0);
  }
});
```

### 同一请求被反复发出 / 页面来回跳转

现象：控制台或日志里同一个请求刷出几十上百条，常伴随 429「超过云服务并发调用上限」，页面持续加载或在两个路由之间来回跳。

排查顺序：

1. 先确认是**重复触发**而不是单点失败：看同一 URL 的重复次数和频率，而不是只看单条错误内容。
2. 找闭环：`请求失败 → 写状态 → effect 重跑或路由跳转 → 组件重挂载 → 再次请求`。重点看权限/登录守卫、`useEffect` 依赖数组、`navigate/router.replace` 调用条件。
3. 常见根因：把限流/网络失败当成"无权限"翻转了判定状态；跳转 effect 依赖了自己写入的判定结果；两个页面互相重定向；请求写入的 state 又是它自己的依赖。

修复要求：

```typescript
// ❌ 错误：查询失败（含 429）就判定为无权限，effect 依赖 isAdmin 立即跳转
useEffect(() => {
  if (!loading && !isAdmin) navigate('/');
}, [loading, user, isAdmin]);

// ✅ 正确：三态 + 失败不翻转 + 只查一次 + replace 跳转
const [access, setAccess] = useState<'loading' | 'granted' | 'denied'>('loading');
useEffect(() => {
  let cancelled = false;
  checkAdmin(user.id)
    .then((ok) => { if (!cancelled) setAccess(ok ? 'granted' : 'denied'); })
    .catch(() => { /* 限流/网络失败：结论未知，保持 loading 并退避重试，禁止置为 denied */ });
  return () => { cancelled = true; };
}, [user.id]);

if (access === 'loading') return <PageLoading />;
if (access === 'denied') return <Navigate to="/" replace />;
```

- 限流（429 / 并发上限）必须指数退避且限制重试次数，不得立即重试。
- 只加 try/catch、只改文案、只加 loading 遮罩不算修复，重复请求仍会继续。
- 修完必须验证：重新触发场景后同一请求不再持续增长（`meoo-cli read-browser-logs --level error` 或控制台）。

## 存储问题

### 文件上传 400 错误

Web/H5 必须使用 ArrayBuffer，不能使用 Blob/File/FormData：
```typescript
import { decode } from 'base64-arraybuffer';

// ✅ 正确
await supabase.storage.from('bucket').upload('path', decode(base64));

// ❌ 错误
await supabase.storage.from('bucket').upload('path', file); // 400 错误
```






## Edge Functions 问题

### CORS 错误

排查 401/CORS 时严禁修改 `src/supabase/client.ts`。先检查业务请求是否使用该文件导出的 `supabaseUrl`、`projectUrlId`、`supabaseAnonKey` / Session，以及裸请求是否携带 `OneDay-App-Id`。

CORS 由 Meoo Cloud 实例域名网关统一校验并生成响应头。不要在函数代码中重复处理 OPTIONS，也不要设置 `Access-Control-Allow-*` 响应头；应继续检查当前 Origin 是否属于实例关联项目，以及请求头、登录态和权限配置是否正确。

## 查询问题

### 查询限制
Supabase 默认限制 1000 行，使用分页：
```typescript
const { data } = await supabase
  .from('posts')
  .select()
  .range(0, 49); // 前50条
```

### 单行查询错误
```typescript
// ✅ 安全
const { data } = await supabase.from('table').select().eq('id', id).maybeSingle();

// ❌ 可能出错
const { data } = await supabase.from('table').select().eq('id', id).single();
```
