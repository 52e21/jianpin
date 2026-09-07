# 基础密码认证 SOP

只在 `authentication.md` 明确命中 `authImplementationSop=basic_auth`，或小程序场景直接路由到本文件时读取。本文件承接用户名/手机号作为用户名 + 密码，以及小程序微信一键登录 + 账号密码登录。

不要用本文件实现邮箱验证码、短信验证码、注册验证码、登录二次校验、忘记密码、找回密码、重置密码或修改手机号。只要出现这些需求，回到 `authentication.md` 路由并读取 `meoo-cloud-auth` 对应子文档。

## 认证方法

### 普通账密登录（默认方式）

Web/H5/Expo 基础密码认证默认采用用户名登录，自动生成 `{username}@meoo.local` 虚拟邮箱以兼容 Supabase Auth。

### 手机号登录

基础密码认证里的手机号登录只是把手机号当作用户名，不发送短信验证码，同样自动生成 `{username}@meoo.local` 虚拟邮箱 + 密码登录。

### 邮箱登录

仅当用户明确要求真实邮箱 + 密码、且不需要邮箱验证码、邮箱确认、忘记密码或找回密码时，才可用 Supabase 原生邮箱密码登录。只要出现邮箱验证码、邮箱确认或邮箱找回密码，必须回到 `authentication.md` 命中 `auth_email_password`。



## 实现要点

### 1. 存储完整会话对象

```typescript
const [session, setSession] = useState<Session | null>(null);
```

### 2. 用户名认证示例

实现用户名或手机号 + 密码登录注册时使用此方式；真实邮箱 + 密码不需要包虚拟邮箱：

```typescript
// 注册
await supabase.auth.signUp({
  email: `${username}@meoo.local`,
  password,
  options: { data: { username } },
});

// 登录
await supabase.auth.signInWithPassword({
  email: `${username}@meoo.local`,
  password,
});
```

内部虚拟邮箱只用于 Supabase Auth 登录，不展示给用户；不要把它写入 `profiles.email`。

### 3. 认证状态监听

```typescript
// 正确：同步状态更新 + 在 effect cleanup 里 unsubscribe
useEffect(() => {
  const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
    setSession(session);
    setUser(session?.user ?? null);

    // 延迟任何 Supabase 调用
    if (session?.user) {
      setTimeout(() => {
        fetchUserProfile(session.user.id);
      }, 0);
    }
  });
  return () => subscription.unsubscribe();
}, []);

// 错误：会导致死锁
supabase.auth.onAuthStateChange(async (event, session) => {
  const profile = await supabase.from('profiles').select(); // 死锁
});
```

## 用户数据表设计


Web/H5/Expo 基础密码认证复用 `authentication.md` 的共享用户数据模型，不在本文单独创建 `profiles`、业务表外键、`user_roles` 或 `has_role`。

- 用户名 + 密码：注册时把用户名写入 `raw_user_meta_data.username`，共享触发器会写入 `profiles.username`。
- 手机号 + 密码：把手机号当作用户名写入 `raw_user_meta_data.username`，不写 `profiles.phone`。
- 不要把 `{username}@meoo.local` 虚拟邮箱写入 `profiles.email`。
- 业务表引用用户、后台角色和管理员权限按 `authentication.md` 的共享模型设计。





## 创建测试用户

```sql
INSERT INTO auth.users (
  instance_id, id, aud, role, email,
  encrypted_password, email_confirmed_at,
  created_at, updated_at,
  confirmation_token, recovery_token,
  email_change_token_new, email_change,
  raw_app_meta_data, raw_user_meta_data,
  is_super_admin
) VALUES (
  '00000000-0000-0000-0000-000000000000',
  gen_random_uuid(), 'authenticated', 'authenticated',
  'testuser@meoo.local',
  crypt('password123', gen_salt('bf')),
  NOW(), NOW(), NOW(),
  '', '', '', '',
  '{"provider":"email","providers":["email"]}'::jsonb,
  '{"username":"testuser"}'::jsonb,
  false
);
```

必需字段：`instance_id`、`::jsonb` 类型转换、空字符串令牌（非 NULL）。


