# ADR-0004：管理端认证与会话

日期：2026-09-29。状态：Accepted（实施决策；完整网页和部署权限待验收）。

管理入口使用FastAPI；密码验证采用pwdlib的Argon2实现，耗时计算由AnyIO线程池承担。Cookie设置和删除交给Starlette。上述库加入锁文件，不自行实现密码散列算法、Cookie编码或JWT签名。

首版只有单管理员，管理服务独立于聊天进程。选用PG服务端不透明会话，浏览器仅持随机会话令牌，库中保存其SHA-256摘要。该摘要处理高熵随机令牌，不替代密码所需的Argon2。会话查询检查过期和当前密码哈希版本；退出删除服务端会话，凭据更换使旧版本无效。后续多实例凭据变更必须统一部署，不能让旧凭据实例继续接受登录。

选择服务端会话是为了即时撤销和已有PG复用。首版不需要JWT跨服务分发，也不为会话额外部署Redis。PG不可用时管理认证失败关闭。admin schema用于组织管理数据；数据库角色授权另行部署，schema本身不构成隔离证明。

所有修改请求校验固定Origin；已登录副作用接口还须校验与会话绑定的CSRF。Cookie为HttpOnly与SameSite=Strict；HTTPS开启Secure，本机HTTP通过SSH隧道访问时明确使用非Secure Cookie，不声称明文公网可安全运行。SecretStr和Pydantic隐藏错误设置不足以阻止FastAPI默认校验响应包含输入，因此另设脱敏异常处理。

登录固定窗口计数保存在PG，先原子认领再执行密码计算，各实例共享每60秒5次尝试额度。部署默认本机单管理员；若未来公开服务或多租户，需重新设计限速维度、恢复机制和入口保护，不把本方案声称为公开服务完整防护。

官方依据：

- [FastAPI密码哈希教程](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)：pwdlib和Argon2用法；本项目不采用教程中的JWT流程。
- [pwdlib用法](https://frankie567.github.io/pwdlib/guide/)：哈希验证与算法封装。
- [Starlette响应Cookie](https://starlette.dev/responses/)：安全属性和匹配路径删除Cookie。

具体验收范围见SPEC-030。浏览器页面、配置发布、CLI、密码初始化/更换运维流程仍需后续实现。
