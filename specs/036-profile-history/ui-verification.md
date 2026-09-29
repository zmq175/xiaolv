# UI验收

Surface：已保存草稿的发布差异、历史版本选择、回滚预览。

Ran：本地Chromium接真实管理服务和PG，在1280×800与390×844完成选择/回滚并截图。artifacts/profile-history-1280.png、profile-history-390.png为合成数据，未上传。状态扫描history-state-coverage.json包含loading/empty/error/disabled/focus/selected/submitting/success全部标记；静态扫描不替代行为验证。浏览器验证历史读取错误、选择错误和重试、乱序响应、回滚丢响应恢复、未保存内容禁用回滚。

Manual：打开两种尺寸截图；移动端差异改为纵向对照，版本按钮用aria-pressed及背景/边框标出选择，版本名称、时间与按钮无重叠。焦点和主次按钮沿用已有样式，文本无HTML渲染。

Skipped：未另跑只取HTML、无浏览器驱动的visual_smoke_test.mjs，使用临时真实服务的Playwright交互/截图验证。没有外部设计服务或云端截图传输。

Planned：运行实例采用版本与心跳、会话权限页面、真实部署验证。历史量增大后的使用体验需要后续实际运营数据复核。
