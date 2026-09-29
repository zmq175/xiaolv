# 验证证据

2026-09-29。使用已确认的浏览器/HTTP测试边界，真实PG、管理子进程和Chromium；成功认证路径不mock自有API。

- 初次浏览器运行缺匹配的Chromium（环境错误，不作TDD红灯）。安装锁定Playwright对应浏览器后，桌面/移动均因/admin/404找不到登录标题失败，构成行为红灯。
- 实现React登录、刷新验证、退出及同源静态资源后2 passed。前端初次构建因CSS类型声明缺失报错，加入vite/client类型后构建通过。
- 会话检查断网时缺重试按钮，用例失败；增加明确的错误状态及重新连接操作后通过。
- 真实429、键盘/提交禁用、退出断网不假报成功、缺构建503/API仍401随后首次验证通过。浏览器/HTTP专项6 passed in 15.62s。
- 使用webapp-ui-skill，素材/页面/截图均本地，未向外部设计服务传输。状态扫描和视觉smoke已执行，其局限及截图人工检查见ui-verification.md。

依赖锁定React19.3.0、TypeScript7.0.2、Vite8.3.1、Playwright1.63.0及npm lock。CI固定官方setup-node提交，Node24构建，安装Chromium和中文字体后执行现有pytest。前端静态构建不提交，运行时不新增Node进程。当前npm安装审计报告0漏洞不代表完整供应链安全审计。

最终全量442 passed in 107.25s，无跳过，包含真实Chromium与PG。npm构建/TypeScript检查、Prettier检查、ruff check/format、mypy 42源文件及git diff --check均通过。截图已在字体修复和最终构建后重新打开检查。

尚未配置发布或上线真实VPS，不能将本页面称作完整管理功能交付。本轮仅本地证据；远程CI状态另行核实，不将工作流文件修改视为CI已成功。
