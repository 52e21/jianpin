# 实时功能

> **强制：** 业务前端的实时订阅必须使用平台生成的 `supabase.channel()`。禁止自建 WebSocket/手工连接 Realtime 端点，禁止重新 `createClient()`。

## 监听数据变化

### 启用表的实时功能
**重要**：需要监听数据实时变化的数据表必须先通过以下指令启动 RealTime 功能
```sql
ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
```

### 监听变化


```typescript
import { supabase } from 'src/supabase/client';

const currentUserId = getCurrentUserId(); // 获取当前用户ID

const channel = supabase
  .channel('messages')
  .on(
    'postgres_changes',
    { event: 'INSERT', schema: 'public', table: 'messages' },
    (payload) => {
      const newMessage = payload.new;
      // 只处理其他用户发送的消息，避免重复显示自己的消息
      if (newMessage.user_id !== currentUserId) {
        setMessages(prev => [...prev, newMessage]);
      }
    }
  )
  .subscribe();

// 发送消息的正确做法
const sendMessage = async (content) => {
  // 1. 立即添加到本地状态（避免延迟）
  const tempMessage = { id: `temp-${Date.now()}`, content, user_id: currentUserId };
  setMessages(prev => [...prev, tempMessage]);

  // 2. 发送到数据库
  const { data, error } = await supabase.from('messages').insert({ content, user_id: currentUserId });
  if (error) {
    // 发送失败时移除本地消息
    setMessages(prev => prev.filter(msg => msg.id !== tempMessage.id));
  }
};

// ✅ 清理以防止内存泄漏
return () => { channel.unsubscribe(); };
```






**注意事项**
- 记得为实时表设置适当的 RLS 策略
- 发送消息成功后，立即手动将新消息对象添加到本地 messages 数组，不要依赖 Realtime 订阅来显示自己发送的消息（避免延迟）
- Realtime 订阅仅用于接收其他用户发送的消息

## 用户在线状态

Supabase 提供实时功能来跟踪用户在线状态并在用户间共享状态。

```typescript
const roomOne = supabase.channel('room_01');

// 同步和跟踪状态
roomOne
  .on('presence', { event: 'sync' }, () => {
    const newState = roomOne.presenceState();
    console.log('sync', newState);
  })
  .on('presence', { event: 'join' }, ({ key, newPresences }) => {
    console.log('join', key, newPresences);
  })
  .on('presence', { event: 'leave' }, ({ key, leftPresences }) => {
    console.log('leave', key, leftPresences);
  })
  .subscribe();

// 发送状态
const userStatus = {
  user: 'user-1',
  online_at: new Date().toISOString(),
};

roomOne.subscribe(async (status) => {
  if (status !== 'SUBSCRIBED') return;
  const presenceTrackStatus = await roomOne.track(userStatus);
  console.log(presenceTrackStatus);
});

// ✅ 清理以防止内存泄漏
return () => { roomOne.unsubscribe(); };
```
