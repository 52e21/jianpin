# 文件存储

> **强制：** 业务前端的上传、下载、删除和 URL 获取必须使用平台生成的 `supabase.storage`。禁止裸 `fetch` / `axios` / `Taro.request` 请求 `/storage/v1`，禁止重新 `createClient()`。

## 创建存储桶

通过 SQL 迁移创建存储桶：

```sql
INSERT INTO storage.buckets (id, name, public)
VALUES ('avatars', 'avatars', true);
```

## 关键上传方法


**必须使用 ArrayBuffer**（通过 `base64-arraybuffer`）进行所有文件上传。使用 `Blob`、`File` 或 `FormData` 会导致 `400 InvalidRequest "No content provided"` 错误。
**注意**：必须通过友好的 Toast 交互提醒用户数据操作结果，特别是操作失败的情况。
**重要约束：必须在前端上传文件。禁止在云函数（Edge Functions）中上传文件**，因为云函数上传的文件无法获取公网访问 URL，会导致前端无法正常访问和显示文件。所有文件上传操作必须在前端（浏览器环境）中进行。

> 记得在 `package.json` 中添加 `base64-arraybuffer` 依赖。

```typescript
import { decode } from 'base64-arraybuffer';

// ✅ 从 base64 字符串上传（必须检查 error）
const { data, error } = await supabase.storage
  .from('avatars')
  .upload('public/avatar1.png', decode('base64FileData'), {
    contentType: 'image/png'
  });

if (error) throw new Error(`上传失败: ${error.message}`);

// 从文件输入上传（先转换为 ArrayBuffer）
const reader = new FileReader();
reader.onload = async (e) => {
  const base64 = (e.target?.result as string).split(',')[1];
  const { data, error } = await supabase.storage
    .from('bucket-name')
    .upload(`path/${file.name}`, decode(base64), {
      contentType: file.type,
    });

  if (error) {
    console.error('上传失败:', error.message);
    return;
  }
};
reader.readAsDataURL(file);
```

```typescript
// ❌ 错误做法 — 会导致 400 错误
const formData = new FormData();
formData.append('file', file);
await supabase.storage.from('bucket').upload('path', formData); // ❌
await supabase.storage.from('bucket').upload('path', blob);     // ❌
await supabase.storage.from('bucket').upload('path', file);     // ❌
```






## 存储 RLS 策略

```sql
-- 创建存储桶的 RLS 策略
CREATE POLICY anon_select_avatars ON storage.objects
FOR SELECT USING (bucket_id = 'avatars');

CREATE POLICY users_insert_avatars ON storage.objects
FOR INSERT WITH CHECK (
  bucket_id = 'avatars' AND
  auth.role() = 'authenticated'
);
```

## Edge Functions 存储限制


**重要**：存储操作应在前端执行，而非 Edge Functions。Edge Functions 使用私有网络 URL，无法提供文件的公开访问。



## 存储模式限制

不要在 `storage` 模式中执行以下操作：
- 创建自定义表或函数
- 删除现有表或函数
- 在现有存储表上创建索引
- 对 `storage.migrations` 执行破坏性操作

管理文件访问请在 `public` 模式中创建辅助函数。
