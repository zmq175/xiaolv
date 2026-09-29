# 会话管理页面验证

2026-09-30，使用webapp-ui-skill，沿用现有同源React管理台，不向外部上传截图或会话数据。skill内共享文档旧相对路径不存在，实际读取skills/_shared中的privacy-policy与visual-verification。

Surface：已登记会话列表、停用/恢复、刷新与游标加载更多。状态文字表达启用/停用，不用颜色作为唯一依据；列表不是在线实例监控。

Ran：真实本地HTTP/PG及Chromium浏览器；1280×800、390×844完成停用/刷新/恢复并验证页面无水平溢出。截图artifacts/conversations-1280.png、conversations-390.png均已打开查看：名称与状态可读，按钮没有覆盖文字，手机布局保留操作空间。额外浏览器用例覆盖首次读取断网、并发版本冲突、写入成功丢响应后使用完全相同幂等键/参数重试，服务端版本只增加一次。

State coverage：加载提示、空列表说明、错误警告、请求期间禁用、未知结果锁定与原操作重试、成功后读取当前状态；复用全局focus-visible和hover样式。会话行没有“选中”交互，selected不适用。运行check_state_coverage.ts报告所有应用状态标记存在，但它只是静态标记扫描，不作为全部交互验收。

Skipped：skill的通用visual_smoke_test.mjs；应用需要带数据库的认证服务和操作准备，已使用仓库真实Playwright测试替代，无静态HTML截图冒充。

Manual：两个截图视觉检查完成。真实QQ、VPS部署和完整自然对话质量不在本次浏览器验证范围。页面恢复不承诺撤回已进入平台的发送。
