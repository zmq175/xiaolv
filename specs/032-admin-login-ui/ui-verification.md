# 页面状态与检查报告

Surface：管理登录及认证状态页面。Primary workflow：错误密码→正确登录→刷新保持→退出→刷新未登录。

| 页面状态 | 实现与证据 |
|---|---|
| Loading | 初始化展示“正在检查登录状态”和aria-busy；源码检查，短暂状态未单独延迟截图 |
| Empty | 密码为空时禁用登录；没有列表或数据空态，列表empty不适用 |
| Error | 真实401/429反馈，浏览器网络中断及重试测试 |
| Disabled / submitting | 浏览器延迟登录响应，确认密码框与提交按钮禁用 |
| Focus | 键盘Tab到按钮并Enter完成真实登录；CSS焦点环，截图可见输入框焦点 |
| Selected | 无标签页/列表选择，本页面不适用 |
| Success | 真正登录成功、刷新服务端验证及真正退出 |

Ran：React/TypeScript/Vite构建；真实Chromium桌面1280×800和移动390×844；skill状态扫描及HTTP视觉smoke。

状态扫描是正则词汇检查，报告missing loading/empty/selected：loading以checking变量和中文文案实现；empty/selected没有对应数据组件，不为了让扫描变绿添加无用状态。检查报告在artifacts/admin-state-coverage.json。

skill visual_smoke_test.mjs结果HTTP200/HTML非空，其自身明确没有截图驱动；截图由独立Playwright测试生成，不将该smoke脚本描述为浏览器验收。报告在artifacts/admin-visual-smoke/summary.json。

Manual：首次截图中文字形为方框，经fc-list确认容器缺中文字体；在/tmp安装Noto CJK并给浏览器设置FONTCONFIG_FILE后重新截图，字体栈明确Noto Sans CJK SC。桌面与移动截图已打开检查：输入/按钮可见、焦点环清楚、无横向溢出或文本遮挡。截图仅本地artifacts/admin-login-1280.png及admin-login-390.png，均为未填密码的合成环境，没有上传外部服务。

Skipped：无外部设计生成服务、无截图上传；无axe/Lighthouse全量审计、真实设备和Safari/Firefox验证。Planned：配置编辑与发布、真实运行概览、会话过期的主动通知和后续更多页面状态。
