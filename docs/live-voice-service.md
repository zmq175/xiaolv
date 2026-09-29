# 在线语音配置（实验阶段）

基于[在线文字服务](live-text-service.md)的全部启动配置和数据库迁移。语音默认关闭；不设置XIAOLV_SPEECH时不会初始化Fish客户端，不给模型提供语音选择。已通过本地PG、HTTP文字模型、Fish官方SDK合成transport与OneBot WebSocket回放，尚未完成真实Fish音色、账单及QQ客户端播放验收。

管理员将XIAOLV_SPEECH设置为JSON对象；密钥由进程环境或部署密钥注入，不在群聊配置，不写入仓库。结构示例：

```json
{
  "api_key": "<从密钥存储注入>",
  "model": "<账户可用的显式Fish模型>",
  "voice_binding_version": "voice-v1",
  "price_version": "<已核对的计价与换汇策略版本>",
  "reservation_cny": "<单次请求的保守人民币预留额>",
  "voices": {"warm": "<管理员登记的供应商音色ID>"},
  "conversations": {"qq:10000:group:20000": ["warm"]},
  "artifact_root": "/var/lib/xiaolv/audio",
  "max_audio_bytes": 4194304,
  "max_total_bytes": 268435456,
  "max_duration_seconds": 20,
  "retention_seconds": 86400,
  "cleanup_interval_seconds": 600,
  "concurrency": 1
}
```

示例占位符不能直接启动。QQ bot账号和会话必须同时位于现有启用路由中；逻辑音色必须已登记。更换音色/价格策略时更新版本。管理员须核对当前服务实际计价单位、最大正文对应费用和换汇余量；reservation_cny仅为保守预留，不是实际费用，也不是供应商扣费上限。非空配置需要正预留额，且不超过XIAOLV_MONTHLY_EXTERNAL_BUDGET_CNY。

语音和文字模型共用external月度金额池，语音使用独立speech-model共享并发池。SDK没有可靠单次费用回执时不自动释放预留；额度耗尽会阻止新请求。当前尚无管理端对账释放入口，必须完成账单核对功能再做长期无人值守部署，不能手工把未知请求当成免费调用。未自动重试收费TTS，失败不自动回退文字。

音频以会话摘要分目录，保存有限长度WAV；仅平台边界转base64。Speech模型只决定逻辑音色、语音内容或文字，不接触路径/URL。原生record复用权限、TTL、epoch、配额及outbox；确认表示平台API成功回执，不等于QQ客户端已试听成功。

清理任务随在线服务启动并按间隔运行，删除保留期前的音频及暂存文件。保留期须大于聊天回合TTL。清理失败只记audio_cleanup_failed固定事件，不输出路径或异常正文；后续周期继续尝试，硬容量限制仍生效。服务停止会取消清理任务；已进入线程的本地文件操作会完成并释放锁，不产生平台发送。

使用具有可靠flock语义的本地Unix文件系统，产物目录应只授权机器人进程。共享目录的实例必须设置相同限额。总量是组件管理文件逻辑字节，不含文件系统块和目录开销；跨主机请另行接对象存储实现，当前不承诺NFS/Windows语义。应监测剩余空间和清理失败；真实部署还需备份/恢复、音色试听和QQ播放验收。
