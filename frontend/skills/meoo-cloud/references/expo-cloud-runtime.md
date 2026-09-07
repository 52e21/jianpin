# Expo Cloud Runtime

本文件是 Expo/create-app 使用 Meoo Cloud、Supabase 和 Edge Functions 的公共约束。任何 `meoo-cloud`、`meoo-cloud-auth` 或 `meoo-*-ai` skill 在 create-app 场景写云服务代码前，都必须先读取本文件和 `skills/expo-project/SKILL.md`。

## 初始化顺序

Expo 项目涉及 Cloud 或 AI 时，遵守 `expo-project` 的顺序：

1. 先替换 `app.json` 中的应用名称。
2. 读取当前 Cloud/AI 能力所需的最小必要文档。
3. 立即执行 `meoo-cli cloud init -d "<应用描述>"`。
4. Cloud 初始化确认完成后，再继续 Expo UI 细节、素材生成、可选原生模块文档读取和业务代码实现。

不要为了读取大量 Expo 模块文档、完善页面样式或下载素材而推迟云服务确认。

## Supabase Client

- `meoo-cli cloud init` 会生成 `src/supabase/client.ts` 和 `src/supabase/types.ts`。
- 业务代码只 import 生成的 client，禁止手写、覆盖或编辑生成的 client。
- 生成的 client 已处理 `react-native-url-polyfill` 和 `expo-secure-store` session storage。
- import 必须按当前文件位置写到 `src/supabase/client` 的相对路径，例如 `../supabase/client`、`../../supabase/client`。
- 禁止使用小程序路径；不要手写、覆盖或移动自动生成的 client。

## Edge Function 调用

Expo 使用 React Native / Expo 环境自带的全局 `fetch`。

```ts
import { projectUrlId, supabase, supabaseUrl } from '../supabase/client'; // 按当前文件层级调整

const session = (await supabase.auth.getSession()).data.session;
const authHeaders = session ? { Authorization: `Bearer ${session.access_token}` } : {};

const response = await fetch(`${supabaseUrl}/functions/v1/function-name`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'OneDay-App-Id': projectUrlId,
    ...authHeaders,
  },
  body: JSON.stringify(payload),
});
```

- `verify_jwt: true` 的函数必须传 `Authorization: Bearer <access_token>`。
- `verify_jwt: false` 的匿名函数不需要额外传 `apikey`。
- 普通 JSON 响应用 `response.json()`。
- 流式响应先检查 `response.body`，存在时才调用 `getReader()`。

```ts
if (!response.body) {
  throw new Error('当前 Expo/RN 运行环境不支持 response.body 流式读取');
}
const reader = response.body.getReader();
```

## 文件上传

Expo/RN 没有浏览器文件输入语义。上传本地文件或图片时：

- 使用全局 `fetch(uri).arrayBuffer()` 获取字节。
- 将 `ArrayBuffer` 或 `Uint8Array` 传给 Supabase Storage `upload()`。
- 根据实际 asset 使用 `mimeType` / `fileName`，缺省时再兜底。
- 禁止 `FileReader`、DOM `<input>`、`File`、`Blob`、`FormData`、`response.blob()`、`response.bytes()`、`Buffer.from()`。

```ts
const response = await fetch(asset.uri);
const arrayBuffer = await response.arrayBuffer();

await supabase.storage.from('images').upload(path, arrayBuffer, {
  contentType: asset.mimeType || 'image/jpeg',
  upsert: true,
});
```

## Auth Redirect

邮箱确认、找回密码或 OAuth 回跳 URL 使用 `expo-linking` 的 `Linking.createURL()` 构造：

```ts
import * as Linking from 'expo-linking';

const redirectTo = Linking.createURL('/auth/callback');
```

回跳页再用 `Linking.useLinkingURL()` 或 `Linking.addEventListener('url', ...)` 解析 URL 并恢复 Supabase session。禁止使用 `window.location`，也不要用 `Linking.openURL()` 来构造 redirect URL。

## 项目路径

Expo 项目业务代码默认放在 `src/` 下：

- `src/app/`
- `src/services/`
- `src/components/`
- `src/hooks/`
- `src/utils/`
- `src/constants/`

`assets/` 保持在项目根目录；Cloud 初始化生成的 Supabase client/types 固定放在 `src/supabase/`，不要移动。

## 禁止混用平台能力

Expo/create-app 中禁止照搬：

- Web/H5：`window`、`document`、`localStorage`、`sessionStorage`、DOM、HTML 标签、`className`、`FileReader`、`Blob`、`FormData`
- 小程序：`@/supabase/client`、`@/lib/sse`、`@/lib/upload`、`Taro.request`

界面必须使用 RN 组件和 `StyleSheet.create`；导航使用 `expo-router`。
