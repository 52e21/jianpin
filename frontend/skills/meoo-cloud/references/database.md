# 数据库设计指南

> **强制：** 业务前端的数据库读写必须使用平台生成的 `supabase` Client（`supabase.from()` / `supabase.rpc()`）。禁止裸 `fetch` / `axios` / `Taro.request` 请求 `/rest/v1`，禁止重新 `createClient()`。

## 设计原则

### 匿名优先
默认支持匿名访问。用户应能在不认证的情况下操作数据，登录仅在明确需要时才实现。

## 表设计规范

- **参考真实 schema**：涉及已有表时，建议运行 `meoo-cli cloud tables` 确认表名、列名、类型和 enum 值，不要凭记忆猜测。注意 tables 不包含全部外键、CHECK、复合 unique/exclusion constraint 定义
- 考虑列的**默认值**和**可空性**，避免插入数据时出错
- 与现有数据兼容，迭代时考虑现有数据结构
- Supabase 默认限制每次查询 **1000 行**，大数据集需要分页
- 所有表都需要启用 RLS，且 RLS 权限设计要与功能实现保持一致
- 使用 UUID 作为 id，在实现功能代码时要注意字段格式与数据库字段类型一致
- **禁止在数据库中存储 base64 编码内容**（图片、音频、附件等），会撑爆行大小并拖垮查询
- **禁止在数据库中存储文件二进制数据**（bytea 大字段、文件内容等）；文件必须走 Storage 存储桶，表里只存 `storage_path` / `public_url` 等引用

## SQL 生成与重试规则

- `cloud query` 只执行 SELECT/INSERT/UPDATE/DELETE；DDL 必须使用 `cloud migrate`
- `INSERT` 必须显式列出目标列，列数量、类型和顺序必须匹配 `cloud tables` 输出
- 不向 generated、identity 或 `is_updatable=false` 的列写值；UUID 不使用 `''`，enum 只使用 `enumValues` 中的值
- 使用 `ON CONFLICT` 前确认目标列存在真实 unique/exclusion constraint；复合约束和外键必须依据已执行的 migration 或系统目录确认，写外键前确认父记录存在
- HTTP 400 是 SQL/PostgreSQL 业务错误，读取具体错误并修正 SQL，禁止原样重试
- query/migrate 收到 502 时执行结果可能不确定，禁止自动重放写操作或 DDL；先读取 schema/数据确认是否已生效

## 约束和验证

### 使用触发器而非 CHECK 约束

```sql
-- ✅ 推荐：验证触发器
CREATE OR REPLACE FUNCTION validate_expire_at()
RETURNS TRIGGER LANGUAGE plpgsql AS \$\$
BEGIN
  IF NEW.expire_at <= now() THEN
    RAISE EXCEPTION 'expire_at must be in the future';
  END IF;
  RETURN NEW;
END;
\$\$;

CREATE TRIGGER validate_expire_at_trigger
  BEFORE INSERT OR UPDATE ON bookings
  FOR EACH ROW EXECUTE FUNCTION validate_expire_at();
```

## RLS 策略设计

### 基本 RLS 配置
```sql
ALTER TABLE your_table ENABLE ROW LEVEL SECURITY;
```

### 策略命名规范

用**英文 snake_case 无引号**，格式 `<scope>_<action>_<table>`，例：`anon_select_posts`、`users_update_own_data`、`admins_select_profiles`。不要用中文或带空格的名字（会和 `--sql "..."` 外层引号冲突）。

### 匿名友好的策略
```sql
-- 所有人可查看
CREATE POLICY anon_select_posts ON posts FOR SELECT USING (true);

-- 所有人可创建
CREATE POLICY anon_insert_posts ON posts FOR INSERT WITH CHECK (true);
```

### 用户数据策略（需要登录功能时）

如果业务需求包含登录、注册、前端登录页、验证码登录、短信验证码、阿里云短信、忘记密码、重置密码、修改手机号、用户管理、管理后台、权限、角色或会员，请先回到 `references/authentication.md` 按 L1-L5 分级分类路由确认最终实现 SOP，再按 `basic_auth.md` 或 `meoo-cloud-auth` 对应子文档设计用户相关表与 RLS。

```sql
-- 用户只能查看自己的数据
CREATE POLICY users_select_own_data ON user_data
FOR SELECT USING (user_id = auth.uid());

-- 用户只能修改自己的数据
CREATE POLICY users_update_own_data ON user_data
FOR UPDATE USING (user_id = auth.uid());
```

### 避免 RLS 权限冲突

**重要**：点赞、评论等功能必须创建独立表，不能在原表中直接添加字段，因为会导致 RLS 权限冲突。

```sql
-- 假设原表有严格的 UPDATE 权限
CREATE POLICY users_update_own_messages ON messages
FOR UPDATE USING (user_id = auth.uid());

-- ❌ 错误：在原表中添加点赞字段
-- 点赞操作变成 UPDATE messages，受限于上面的策略
ALTER TABLE messages ADD COLUMN likes INTEGER DEFAULT 0;

-- ✅ 正确：创建独立表
-- 点赞操作是 INSERT message_likes，可以设置不同的权限
CREATE TABLE message_likes (
  message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
  user_id UUID,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 任何人都能点赞
CREATE POLICY anon_insert_message_likes ON message_likes FOR INSERT WITH CHECK (true);
```

## 用户配置文件(需要登录功能时）

认证相关的 `profiles` 表、`handle_new_user` 触发器、业务表用户外键、`user_roles` 角色权限表、`has_role` 函数等以 `references/authentication.md` 的共享用户数据模型为准；`basic_auth.md`、`auth-email-password.md` 和 `auth-sms-password.md` 只补充各自认证标识的写入规则。
如果需求涉及找回密码、重置密码、修改手机号或验证码登录，先按 `references/authentication.md` 的 L1-L5 分级分类路由完成询问，再读取 `meoo-cloud-auth` 对应子文档；不能只按数据库表结构直接实现。

## 避免修改保留模式
不要操作这些 Supabase 保留模式：
- `auth` · `storage` · `realtime` · `supabase_functions` · `vault`

可以引用 `auth.users(id)` 作为外键，但不能修改模式结构。

## 查询最佳实践
**注意**：必须通过友好的 Toast 交互提醒用户数据操作结果，特别是操作失败的情况。
```typescript
// ✅ 正确：必须检查 error 对象
const { data, error } = await supabase
  .from('profiles')
  .select()
  .eq('id', id)
  .maybeSingle();

if (error) {
  console.error('数据库错误:', error.message);
  throw new Error(`查询失败: ${error.message}`);
}

if (!data) { /* 处理未找到的情况 */ }

// ✅ 分页查询
const { data, error } = await supabase
  .from('posts')
  .select()
  .range(0, 49); // 前50条记录

if (error) throw new Error(error.message);

// ❌ 错误：忽略 error 对象会导致静默失败
const { data } = await supabase.from('profiles').select();
```

### 写操作必须校验影响行数（RLS 静默失败）

**重要**：RLS 拦截 INSERT / UPDATE / DELETE 时，Supabase 客户端**不会抛错**，`error` 为 `null`，仅返回空数组。仅判断 `error` 会让前端误报"成功"——这是 RLS 策略问题最常见的隐性表现。

```typescript
// ❌ 错误：error 为 null 不代表写入成功，可能被 RLS 拦截
const { error } = await supabase.from('posts').insert({ title: 'x' });
if (error) throw new Error(error.message);
toast.success('保存成功'); // 实际可能 0 行写入

// ✅ 正确：用 .select() 拿回写入的行，长度为 0 视为失败
const { data, error } = await supabase
  .from('posts')
  .insert({ title: 'x' })
  .select();

if (error) throw new Error(error.message);
if (!data || data.length === 0) {
  throw new Error('写入失败：可能被 RLS 策略拦截，请检查表的 INSERT 策略');
}
```

UPDATE / DELETE 同理：必须 `.select()` 拿到受影响的行，长度为 0 时一律视为失败并提示用户。

## 常见问题

### RLS 策略必须匹配功能
如果应用没有登录功能，数据应该公开可见。策略名称应反映实际功能需求。

### 避免 RLS 无限递归
RLS 无限递归通常发生在策略互相引用时，必须避免会导致无限递归的错误情况：
```sql
-- ❌ 错误：导致无限递归
CREATE POLICY admins_select_profiles ON profiles
FOR SELECT USING (
  (SELECT role FROM profiles WHERE id = auth.uid()) = 'admin'
);

-- ✅ 正确：使用 SECURITY DEFINER 函数
CREATE FUNCTION public.has_role(_user_id UUID, _role TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = public
AS \$\$
  SELECT EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role = _role)
\$\$;

CREATE POLICY admins_select_profiles ON profiles
FOR SELECT USING (public.has_role(auth.uid(), 'admin'));
```

**关键**：权限函数必须使用 `SECURITY DEFINER`，基础权限表策略保持简单。
