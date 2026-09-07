---
name: react-design
description: React 19 + Vite + TanStack Router + shadcn/ui 脚手架的工程规范（路由、依赖、沙箱约束）。
allowed_create_modes:
  - create-desktop
---

# React Design 项目规范

> 模板文件列表与正文在 skill 加载时**首轮**注入（`shareFiles`），后续轮次靠对话历史携带，压缩后可能丢失。

## 预置组件与自动生成

| 路径 | 用法 |
|------|------|
| `src/components/ui/**` | 46 个 shadcn 已预置，直接 `import from "@/components/ui/{name}"`；日常勿 Read 全文，仅自定义源码时 Read 单个文件 |
| `src/routeTree.gen.ts` | Vite 插件自动生成，禁止手改；`pnpm run dev` / `pnpm run build` 都会更新 |

## 工程红线

- `package.json` / `index.html` 中 `meoo-app-name` 占位符勿改（用户明确要求改标题除外）
- `vite.config.ts` 锁定字段勿改：`server.port` / `strictPort` / `host` / `build.outDir` / `build.assetsDir`（细则见已注入的 vite.config.ts）
- 依赖：改 `package.json` 后 `pnpm install`；禁止 `pnpm i <pkg>` 单装；shadcn/Radix 已预置，禁止重复安装
- 动效：CSS keyframes 或 `tw-animate-css`；禁止 framer-motion 等
- 单文件软上限约 260 行；新 UI 写 `src/components/`，文件名唯一。例外：内联了紧耦合父子组件的文件（如拖拽容器+子项）可到约 320 行，不要为了压行数把耦合组件拆成多文件

## 路由

- 页面放 `src/routes/`，一页一文件 + `createFileRoute`；勿把多页堆进 `index.tsx`
- `index.tsx` 只是 `/` 首页占位，须整体替换；`routeTree.gen.ts` 禁止手改（`build`/`dev` 都会更新）
- 点号 = 路径：`posts.tsx`→`/posts`；`$` = 动态段；列表+详情用 `posts_.$id`（后缀 `_` 打断嵌套），勿写 `posts.$id` 却漏 `Outlet`
- 仅部分页共享壳时用 `_layout`（前缀 `_` 不进 URL）+ `_layout.index`，并删除原 `index.tsx`
- `createFileRoute` 写 route id（可含 `/_layout/...`、`/posts_/$id`）；`Link`/`navigate` 写 URL（无 `_layout`）+ `params`
- 只有真正包住子路由的 layout 才放 `<Outlet />`

```tsx
// _layout.tsx
export const Route = createFileRoute('/_layout')({
  component: () => (<div><Outlet />{/* 共享壳 */}</div>),
})
// _layout.index.tsx       → '/_layout/'          → /
// _layout.posts.tsx       → '/_layout/posts'     → /posts
// _layout.posts_.$id.tsx  → '/_layout/posts_/$id'→ /posts/$id
// <Link to="/posts/$id" params={{ id }} />  // 不要 to="/_layout/..."
```

## 组件

- shadcn/ui：已预置在 `src/components/ui/`，直接 `import from "@/components/ui/{name}"` 使用
- **导出形式统一**：自建组件一律具名导出 `export function Xxx`，禁止 `export default`；import 侧一律 `import { Xxx } from './Xxx'`（与预置 shadcn 组件保持一致，避免 default/具名混用导致构建报 "default is not exported"）
- **紧耦合父子组件写同一个文件**：拖拽容器与其可拖拽/可点击子项、共享 pointer 捕获/ref/focus 的组件，把子组件直接 `function Child(){...}` 内联在父文件内，事件逻辑文件内闭环；不要为它们各拆一个文件再靠 props 层层传回调
- 扩展 shadcn：用 `cva` + `cn()`（`src/lib/utils.ts`）；禁止内联条件 class 堆砌
- 图标：`lucide-react`（已内置）

## 移动端点击交互

**普通点击统一使用 React `onClick`，禁止为兼容移动端叠加 Touch 事件**——浏览器会为正常触摸合成 click；额外绑定 `onTouchStart` / `onTouchEnd` 容易重复触发、产生 ghost click，或因 `preventDefault()` 抑制 click。只有连续手势确实需要原始指针序列时才使用 Pointer Events。

| 风险位置 | 禁止或必查模式 | 后果与正确实现 |
|---------|---------------|---------------|
| 普通按钮、链接 | 同一元素同时绑定 `onClick` 与 `onTouchStart` / `onTouchEnd` | 可能重复触发或互相抑制；只保留 `onClick` |
| Touch / capture 监听器 | 无必要地调用 `preventDefault()` | 可能阻止浏览器合成 click；仅在必须阻止滚动/缩放时使用 |
| `html`、`body`、`#root`、`#app` 或共同祖先 | `pointer-events: none`、`inert`、全局禁用态 | 整棵应用树不可交互；禁用范围必须收窄到实际目标 |
| overlay、Drawer、Dialog 遮罩 | 隐藏后仍以高 `z-index` 或透明 `fixed inset-0` 层覆盖页面 | 会不可见地拦截点击；关闭后卸载，或切为 `pointer-events-none` |
| 交互回调与状态锁 | 回调未执行、锁未释放、状态只更新局部副本 | 点击事件存在但业务无结果；验证回调入口和最终状态归属 |

- **多个控件同时失效先查公共链路**：依次检查 console 与初始化/hydration、全屏覆盖层与 `z-index`、共同祖先的交互属性、capture/`preventDefault()`、回调与状态锁；最后才判断特定浏览器兼容性。禁止逐个控件重复补事件。

## 拖拽实现（看板/列表排序/跨容器移动）

**统一用浏览器原生 HTML5 拖放 API，四件套缺一不可**——最常见的失败就是漏掉 `onDrop`，导致能拖起来但松手没反应：

| 位置 | 必需属性 | 作用 |
|------|---------|------|
| 被拖元素 | `draggable` | 允许拖动，缺了拖不起来 |
| 被拖元素 | `onDragStart` | 用 `e.dataTransfer.setData()` 写入被拖 id |
| 放置容器 | `onDragOver` + **必须 `e.preventDefault()`** | 不 preventDefault 则浏览器禁止放置，`onDrop` 永不触发 |
| 放置容器 | **`onDrop`** | 读 `e.dataTransfer.getData()` 并执行移动；**漏掉它拖拽必然无效** |

- **禁止与 pointer 方案混用**：不要同时写 `setPointerCapture` / `onPointerDown` 手搓拖拽。HTML5 `dragstart` 触发后浏览器已接管指针序列，pointer capture 会与之互相打断，两套都失效。拖拽二选一，看板/排序场景一律用 HTML5 拖放。
- **跨容器移动必须由共同父级持有状态**：被拖项在容器 A、放到容器 B，只有同时拥有 A/B 数据的父级（通常是页面）能完成移动。因此容器组件必须接收一个上报回调（如 `onMoveItem(itemId, toContainerId, toIndex)`）并在 `onDrop` 里调用；容器自己 setState 改不动别人的数据。
- 同容器内排序同理：`onDrop` 时算出目标 index 并通过回调上报。

## 样式写法

本脚手架用 Tailwind v4：`src/styles.css` 是唯一 design system，组件通过 theme utility 消费 token。

**标准路径**：用 `oklch` 定义语义变量 → `@theme inline` 映射为 `--color-*` / `--font-*` / `--radius-*` → 组件写 `bg-primary`、`text-foreground`、`from-energy` 这类 utility。新增颜色走同一路径；优先复用已有 shadcn token（`--background`、`--primary` 等）。

**色值套数**：
- 纯深色或纯浅色：只写 `:root` 一套，删除模板里多余的 `.dark`
- 非纯色：默认写两套——`:root` + `.dark`，语义完整且数值不同

```css
/* src/styles.css — 定义 + 注册 */
:root { --energy: oklch(0.7 0.18 45); }
@theme inline { --color-energy: var(--energy); }
```

```tsx
/* 组件 — 只写 theme utility */
<div className="bg-energy text-primary-foreground from-energy to-primary" />
```

滚动入场用模板 `reveal` / `reveal-up` 等 class（见 `src/lib/reveal-engine.ts`）。
